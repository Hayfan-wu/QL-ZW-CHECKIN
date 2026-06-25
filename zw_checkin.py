# -*- coding: utf-8 -*-
"""
@File         : zw_checkin.py
@Author       : Hayfan-wu
@Date         : 2025-06-25
@Description  : 中望技术社区自动签到脚本（青龙面板版）
@Version      : 3.0.0

环境变量:
  ZWSOFT_USERNAME  - 中望社区账号（手机号/邮箱），多账号用换行或&分隔
  ZWSOFT_PASSWORD  - 中望社区密码，多账号用换行或&分隔（与账号一一对应）
  ZWSOFT_NOTIFY    - 通知级别，0=关闭 1=仅异常 2=全部通知（默认1）
  ZWSOFT_DEBUG     - 调试模式，true/false（默认false）
  ZWSOFT_MODE      - 运行模式，api=纯API模式 selenium=浏览器模式 auto=自动尝试（默认auto）

依赖库:
  requests>=2.28.0
  pycryptodome>=3.15.0  (API模式需要，用于RSA密码加密)

cron: 0 0 1 * * *
定时规则：每天凌晨1点执行

使用说明：
  1. 在青龙面板环境变量中添加 ZWSOFT_USERNAME 和 ZWSOFT_PASSWORD
  2. 多账号格式：每行一个账号，密码与账号按顺序一一对应
  3. 推荐使用 auto 模式，自动尝试 API 模式，失败自动降级到 Selenium
  4. 如果 API 模式不可用，可切换为 selenium 模式（需额外安装依赖）

更新日志 v3.0.0:
  - 修复API登录模式，使用正确的 /Account/UserLogin 接口
  - 添加RSA密码加密（与JSEncrypt兼容）
  - 优化登录流程，提高成功率
  - 完善错误处理和日志输出
"""

import os
import sys
import re
import time
import json
import base64
import hashlib
import secrets
import urllib.parse
import requests
from datetime import datetime

# 尝试导入RSA加密库
try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    HAS_RSA = True
except ImportError:
    HAS_RSA = False

# ==================== 配置区域 ====================

ENV_USERNAME = 'ZWSOFT_USERNAME'
ENV_PASSWORD = 'ZWSOFT_PASSWORD'
ENV_NOTIFY = 'ZWSOFT_NOTIFY'
ENV_DEBUG = 'ZWSOFT_DEBUG'
ENV_MODE = 'ZWSOFT_MODE'

# 中望社区URL配置
TOKEN_URL = 'https://accounts.zwsoft.cn/connect/token'
AUTHORIZE_URL = 'https://accounts.zwsoft.cn/connect/authorize'
LOGIN_PAGE_URL = 'https://accounts.zwsoft.cn/Account/Login'
LOGIN_API_URL = 'https://accounts.zwsoft.cn/Account/UserLogin'
GET_PUBKEY_URL = 'https://accounts.zwsoft.cn/Common/Getpubkeys'
FORUM_BASE = 'https://forum.zwsoft.cn'
FORUM_REST = f'{FORUM_BASE}/wp-json/b2/v1'
CHECKIN_URL = f'{FORUM_REST}/userMission'
USER_MISSION_URL = f'{FORUM_REST}/getUserMission'
LOGIN_CALLBACK = f'{FORUM_BASE}/wp-content/themes/zwforumchild/login.php'

# 客户端配置（从论坛登录流程抓包获取）
CLIENT_ID = 'Client_zw_tech_forum'
SCOPE = 'openid email phone profile offline_access ZMS.UserDetails.Write ZMS.UserDetails.Read'

# ==================== 通知模块 ====================

try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

NOTIFY_LEVEL = int(os.getenv(ENV_NOTIFY, '1'))
DEBUG = os.getenv(ENV_DEBUG, 'false').lower() == 'true'
RUN_MODE = os.getenv(ENV_MODE, 'auto').lower()


def log_debug(msg):
    """调试日志"""
    if DEBUG:
        print(f"[DEBUG] {msg}")


def log_info(msg):
    """信息日志"""
    print(f"[INFO] {msg}")


def log_error(msg):
    """错误日志"""
    print(f"[ERROR] {msg}")


def notify(title, content, level=1):
    """
    发送通知
    
    Args:
        title: 通知标题
        content: 通知内容
        level: 通知级别，1=重要通知 2=普通通知
    """
    print(f"\n{'='*50}")
    print(f"📢 {title}")
    print(f"{'-'*50}")
    print(f"{content}")
    print(f"{'='*50}\n")
    
    if HAS_NOTIFY and NOTIFY_LEVEL >= level:
        try:
            ql_send(title, content)
        except Exception as e:
            log_error(f"发送通知失败: {e}")


# ==================== 账号读取 ====================

def get_accounts():
    """
    从环境变量读取多账号列表
    
    Returns:
        list: [{'username': 'xxx', 'password': 'xxx'}, ...]
    """
    username_env = os.getenv(ENV_USERNAME, '')
    password_env = os.getenv(ENV_PASSWORD, '')
    
    if not username_env.strip() or not password_env.strip():
        log_error(f"未找到环境变量 {ENV_USERNAME} 或 {ENV_PASSWORD}")
        return []
    
    # 解析用户名列表
    if '\n' in username_env:
        usernames = [line.strip() for line in username_env.splitlines() if line.strip()]
    elif '&' in username_env:
        usernames = [acc.strip() for acc in username_env.split('&') if acc.strip()]
    else:
        usernames = [username_env.strip()]
    
    # 解析密码列表
    if '\n' in password_env:
        passwords = [line.strip() for line in password_env.splitlines() if line.strip()]
    elif '&' in password_env:
        passwords = [pwd.strip() for pwd in password_env.split('&') if pwd.strip()]
    else:
        passwords = [password_env.strip()]
    
    # 检查账号密码数量是否匹配
    if len(usernames) != len(passwords):
        log_error(f"账号数量({len(usernames)})与密码数量({len(passwords)})不匹配")
        return []
    
    accounts = []
    for i in range(len(usernames)):
        accounts.append({
            'username': usernames[i],
            'password': passwords[i]
        })
    
    log_info(f"共读取到 {len(accounts)} 个账号")
    return accounts


# ==================== PKCE 工具函数 ====================

def generate_code_verifier():
    """生成 PKCE code_verifier"""
    return secrets.token_urlsafe(64)


def generate_code_challenge(verifier):
    """生成 PKCE code_challenge (S256)"""
    code_challenge = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(code_challenge).rstrip(b'=').decode('ascii')


def generate_state():
    """生成 state 参数"""
    return secrets.token_hex(16)


# ==================== RSA 加密函数 ====================

def rsa_encrypt(public_key_pem, plaintext):
    """
    使用RSA公钥加密（与JSEncrypt兼容，PKCS1_v1_5填充）
    
    Args:
        public_key_pem: PEM格式的公钥字符串
        plaintext: 要加密的明文字符串
    
    Returns:
        str: Base64编码的密文
    """
    if not HAS_RSA:
        raise ImportError("需要安装pycryptodome库: pip install pycryptodome")
    
    # 解析公钥
    public_key = RSA.import_key(public_key_pem)
    
    # 创建加密器（PKCS1_v1_5填充，与JSEncrypt兼容）
    cipher = PKCS1_v1_5.new(public_key)
    
    # 加密
    ciphertext = cipher.encrypt(plaintext.encode('utf-8'))
    
    # 返回Base64编码的结果
    return base64.b64encode(ciphertext).decode('utf-8')


# ==================== API 模式核心功能 ====================

class ZwCheckinAPI:
    """中望社区签到 - API模式（授权码模式 + PKCE + RSA加密）"""
    
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.b2_token = None  # 论坛JWT token
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.code_verifier = None
        self.code_challenge = None
        self.state = None
        self.public_key = None  # RSA公钥
    
    def _get_public_key(self):
        """
        获取RSA公钥
        
        Returns:
            bool: 是否成功获取
        """
        log_debug("正在获取RSA公钥...")
        
        try:
            response = self.session.get(GET_PUBKEY_URL, timeout=30)
            if response.status_code == 200:
                self.public_key = response.json()
                log_debug(f"公钥获取成功，长度: {len(self.public_key)} 字符")
                return True
            else:
                log_error(f"获取公钥失败: HTTP {response.status_code}")
                return False
        except Exception as e:
            log_error(f"获取公钥异常: {e}")
            return False
    
    def _get_login_page(self):
        """
        访问登录页面，获取表单参数
        
        Returns:
            dict: 表单参数字典，失败返回None
        """
        log_debug("正在访问登录页面...")
        
        try:
            # 1. 生成 PKCE 参数
            self.code_verifier = generate_code_verifier()
            self.code_challenge = generate_code_challenge(self.code_verifier)
            self.state = generate_state()
            
            log_debug(f"code_verifier: {self.code_verifier[:20]}...")
            log_debug(f"code_challenge: {self.code_challenge[:20]}...")
            log_debug(f"state: {self.state}")
            
            # 2. 构建授权URL
            auth_params = {
                'response_type': 'code',
                'client_id': CLIENT_ID,
                'scope': SCOPE,
                'redirect_uri': LOGIN_CALLBACK,
                'state': self.state,
                'code_challenge': self.code_challenge,
                'code_challenge_method': 'S256',
                'token': f'login_time_{int(time.time())}'
            }
            
            auth_url = f'{AUTHORIZE_URL}?{urllib.parse.urlencode(auth_params)}'
            log_debug(f"授权URL: {auth_url[:100]}...")
            
            # 3. 访问授权URL（会跳转到登录页）
            response = self.session.get(auth_url, allow_redirects=True, timeout=30)
            log_debug(f"登录页URL: {response.url[:100]}...")
            log_debug(f"登录页状态码: {response.status_code}")
            
            page_html = response.text
            
            # 4. 提取表单隐藏字段
            # 提取 __RequestVerificationToken
            token_match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page_html)
            request_token = token_match.group(1) if token_match else ''
            
            # 提取 ReturnUrl
            return_url_match = re.search(r'name="ReturnUrl"[^>]*value="([^"]+)"', page_html)
            return_url = return_url_match.group(1) if return_url_match else ''
            
            # 也可以从 URL 中获取
            if not return_url:
                parsed = urllib.parse.urlparse(response.url)
                query_params = urllib.parse.parse_qs(parsed.query)
                return_url = query_params.get('ReturnUrl', [''])[0]
            
            # 提取 ClientId
            client_id_match = re.search(r'name="ClientId"[^>]*value="([^"]+)"', page_html)
            client_id = client_id_match.group(1) if client_id_match else CLIENT_ID
            
            log_debug(f"RequestVerificationToken: {request_token[:20]}..." if request_token else "未找到RequestVerificationToken")
            log_debug(f"ReturnUrl: {return_url[:50]}..." if return_url else "未找到ReturnUrl")
            log_debug(f"ClientId: {client_id}")
            
            if not request_token or not return_url:
                log_error("未能从登录页面提取到必要的表单参数")
                return None
            
            return {
                'request_token': request_token,
                'return_url': return_url,
                'client_id': client_id,
                'page_url': response.url
            }
            
        except Exception as e:
            log_error(f"访问登录页面异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return None
    
    def login(self):
        """
        使用API登录（RSA加密密码 + 授权码模式 + PKCE）
        
        Returns:
            bool: 是否登录成功
        """
        log_info(f"正在登录账号: {self.username}")
        
        if not HAS_RSA:
            log_error("未安装pycryptodome，无法使用API模式登录")
            log_error("请安装: pip install pycryptodome")
            return False
        
        try:
            # 1. 获取RSA公钥
            if not self._get_public_key():
                log_error("获取公钥失败，无法继续登录")
                return False
            
            # 2. 访问登录页面，获取表单参数
            login_params = self._get_login_page()
            if not login_params:
                log_error("获取登录页面参数失败")
                return False
            
            # 3. 加密密码
            log_debug("正在加密密码...")
            try:
                encrypted_password = rsa_encrypt(self.public_key, self.password)
                log_debug(f"密码加密成功: {encrypted_password[:20]}...")
            except Exception as e:
                log_error(f"密码加密失败: {e}")
                return False
            
            # 4. 构建登录请求数据
            login_data = {
                'Agreement': 'true',
                'Username': self.username,
                'Password': encrypted_password,
                'ReturnUrl': login_params['return_url'],
                'RememberLogin': 'false',
                'LoginType': 'Pwd',
                'ClientId': login_params['client_id'],
                'ActUser': '',
                'ActCorp': '',
                '__RequestVerificationToken': login_params['request_token']
            }
            
            log_debug(f"登录数据:")
            log_debug(f"  Username: {self.username}")
            log_debug(f"  Password: {encrypted_password[:20]}...")
            log_debug(f"  ReturnUrl: {login_params['return_url'][:50]}...")
            log_debug(f"  LoginType: Pwd")
            
            # 5. 发送登录请求
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': login_params['page_url'],
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }
            
            log_debug("正在发送登录请求...")
            
            response = self.session.post(
                LOGIN_API_URL,
                data=login_data,
                headers=headers,
                allow_redirects=False,
                timeout=30
            )
            
            log_debug(f"登录响应状态码: {response.status_code}")
            log_debug(f"登录响应内容: {response.text[:500]}")
            
            # 6. 解析登录响应
            if response.status_code != 200:
                log_error(f"登录请求失败: HTTP {response.status_code}")
                return False
            
            try:
                result = response.json()
            except:
                log_error("登录响应不是有效的JSON格式")
                log_debug(f"响应内容: {response.text[:500]}")
                return False
            
            status = result.get('status')
            msg = result.get('msg', {})
            
            # status=1: 登录成功，跳转到x.msg中的URL
            if status == 1:
                log_info("登录成功，正在获取授权码...")
                
                # msg是跳转URL，需要访问它来获取授权码
                redirect_url = msg if isinstance(msg, str) else msg.get('value', '')
                
                if not redirect_url:
                    log_error("登录成功但未获取到跳转URL")
                    return False
                
                # 如果URL是相对路径，补全
                if redirect_url.startswith('/'):
                    redirect_url = f'https://accounts.zwsoft.cn{redirect_url}'
                
                log_debug(f"跳转URL: {redirect_url[:100]}...")
                
                # 访问跳转URL（会经过多次重定向，最终到callback页面）
                callback_response = self.session.get(
                    redirect_url,
                    allow_redirects=True,
                    timeout=30
                )
                
                log_debug(f"最终URL: {callback_response.url[:100]}...")
                
                # 7. 检查是否跳转到了callback页面
                if 'zwforumchild/login.php' in callback_response.url:
                    log_debug("已跳转到论坛回调页面")
                    
                    # 从 URL 中提取 code
                    parsed = urllib.parse.urlparse(callback_response.url)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    code = query_params.get('code', [''])[0]
                    
                    if code:
                        log_debug(f"获取到授权码: {code[:20]}...")
                        
                        # 8. 用授权码换取 token
                        return self._exchange_token(code)
                    else:
                        log_error("登录失败：未获取到授权码")
                        log_debug(f"回调URL参数: {query_params}")
                        return False
                else:
                    # 检查是否已经有b2_token cookie
                    b2_token_cookie = self.session.cookies.get('b2_token')
                    if b2_token_cookie:
                        self.b2_token = b2_token_cookie
                        log_info("登录成功（获取到 b2_token）")
                        return True
                    
                    log_error(f"登录失败：未跳转到预期的回调页面")
                    log_debug(f"当前URL: {callback_response.url[:100]}")
                    return False
            
            # status=0: 登录失败
            elif status == 0:
                error_msg = msg.get('value', '未知错误') if isinstance(msg, dict) else str(msg)
                log_error(f"登录失败: {error_msg}")
                return False
            
            # status=2: 其他跳转
            elif status == 2:
                log_debug(f"登录状态=2，跳转URL: {msg}")
                # 尝试访问跳转URL
                redirect_url = msg if isinstance(msg, str) else msg.get('value', '')
                if redirect_url:
                    if redirect_url.startswith('/'):
                        redirect_url = f'https://accounts.zwsoft.cn{redirect_url}'
                    callback_response = self.session.get(
                        redirect_url,
                        allow_redirects=True,
                        timeout=30
                    )
                    
                    # 检查是否有b2_token
                    b2_token_cookie = self.session.cookies.get('b2_token')
                    if b2_token_cookie:
                        self.b2_token = b2_token_cookie
                        log_info("登录成功（获取到 b2_token）")
                        return True
                    
                    # 检查URL中是否有code
                    if 'code=' in callback_response.url:
                        parsed = urllib.parse.urlparse(callback_response.url)
                        query_params = urllib.parse.parse_qs(parsed.query)
                        code = query_params.get('code', [''])[0]
                        if code:
                            return self._exchange_token(code)
                
                log_error("登录失败：状态码=2但未能完成登录")
                return False
            
            # status=3: 需要重置密码等
            elif status == 3:
                error_msg = msg.get('value', '需要其他操作') if isinstance(msg, dict) else str(msg)
                log_error(f"登录失败: {error_msg}")
                return False
            
            else:
                log_error(f"登录失败：未知状态码 {status}")
                log_debug(f"完整响应: {json.dumps(result, ensure_ascii=False)}")
                return False
                
        except Exception as e:
            log_error(f"登录异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return False
    
    def _exchange_token(self, code):
        """
        用授权码换取 access token
        
        Args:
            code: 授权码
        
        Returns:
            bool: 是否成功
        """
        log_debug("正在用授权码换取token...")
        
        try:
            token_data = {
                'client_id': CLIENT_ID,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': LOGIN_CALLBACK,
                'code_verifier': self.code_verifier
            }
            
            token_response = self.session.post(
                TOKEN_URL,
                data=token_data,
                timeout=30
            )
            
            log_debug(f"Token响应状态码: {token_response.status_code}")
            
            if token_response.status_code == 200:
                token_result = token_response.json()
                log_debug(f"Token响应: access_token={token_result.get('access_token', '')[:20]}...")
                
                # 访问回调页面，获取 b2_token cookie
                # 先检查当前是否已有b2_token
                b2_token_cookie = self.session.cookies.get('b2_token')
                
                if b2_token_cookie:
                    self.b2_token = b2_token_cookie
                    log_info("登录成功（获取到 b2_token）")
                    log_debug(f"b2_token: {self.b2_token[:20]}...")
                    return True
                else:
                    # 尝试手动访问回调页面来设置 cookie
                    log_debug("未找到 b2_token cookie，尝试手动访问回调页面...")
                    callback_url = f'{LOGIN_CALLBACK}?code={code}&state={self.state}'
                    callback_response = self.session.get(callback_url, allow_redirects=True, timeout=30)
                    
                    b2_token_cookie = self.session.cookies.get('b2_token')
                    if b2_token_cookie:
                        self.b2_token = b2_token_cookie
                        log_info("登录成功（获取到 b2_token）")
                        return True
                    else:
                        log_error("登录失败：未获取到 b2_token")
                        log_debug(f"所有cookies: {dict(self.session.cookies)}")
                        return False
            else:
                log_error(f"换取Token失败: {token_response.status_code}")
                log_debug(f"Token响应内容: {token_response.text[:500]}")
                return False
                
        except Exception as e:
            log_error(f"换取Token异常: {e}")
            return False
    
    def get_mission_status(self):
        """
        获取签到状态
        
        Returns:
            dict: 签到状态信息
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.b2_token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.post(
                USER_MISSION_URL,
                headers=headers,
                json={},
                timeout=30
            )
            
            log_debug(f"获取签到状态响应: {response.status_code} - {response.text[:300]}")
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_mission_data(data)
            else:
                log_error(f"获取签到状态失败: {response.status_code}")
                log_debug(f"响应内容: {response.text[:500]}")
                return None
                
        except Exception as e:
            log_error(f"获取签到状态异常: {e}")
            return None
    
    def _parse_mission_data(self, data):
        """
        解析签到数据（根据实际API返回格式）
        
        Args:
            data: API返回的数据
            
        Returns:
            dict: 解析后的签到信息
        """
        result = {
            'already_checked': False,
            'consecutive_days': 0,
            'points_earned': 0,
            'total_points': 0
        }
        
        # 实际格式: {"mission":{"date":"","credit":0,"always":0,"tk":{"days":0,"credit":0,"bs":"3"},"my_credit":0,"current_user":0}}
        if isinstance(data, dict):
            mission = data.get('mission', {})
            
            if isinstance(mission, dict):
                # 今日积分（如果已签到，credit > 0）
                today_credit = mission.get('credit', 0)
                if today_credit > 0:
                    result['already_checked'] = True
                    result['points_earned'] = int(today_credit)
                
                # 总积分
                result['total_points'] = int(mission.get('my_credit', 0))
                
                # 连续签到天数（从 tk.days 或其他字段）
                tk = mission.get('tk', {})
                if isinstance(tk, dict):
                    result['consecutive_days'] = int(tk.get('days', 0))
                
                # 检查 date 字段判断是否今日已签到
                if mission.get('date'):
                    # 有日期说明已签到
                    result['already_checked'] = True
                
                # current_user > 0 表示已登录
                if mission.get('current_user', 0) == 0:
                    log_debug("current_user=0，可能未登录或token无效")
        
        log_debug(f"解析签到数据: {result}")
        return result
    
    def checkin(self):
        """
        执行签到
        
        Returns:
            dict: {success, message, consecutive_days, points_earned, total_points}
        """
        log_info("开始执行签到...")
        
        try:
            # 先获取当前状态
            current_status = self.get_mission_status()
            
            if current_status and current_status.get('already_checked'):
                log_info("今日已经签到过了")
                return {
                    'success': True,
                    'message': '今日已签到',
                    'consecutive_days': current_status.get('consecutive_days', 0),
                    'points_earned': current_status.get('points_earned', 0),
                    'total_points': current_status.get('total_points', 0)
                }
            
            # 执行签到
            headers = {
                'Authorization': f'Bearer {self.b2_token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.post(
                CHECKIN_URL,
                headers=headers,
                json={},
                timeout=30
            )
            
            log_debug(f"签到响应: {response.status_code} - {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                
                # 检查是否有错误
                if data.get('code') == 'user_error' or data.get('code') == 403:
                    error_msg = data.get('message', '签到失败')
                    log_error(f"签到失败: {error_msg}")
                    return {
                        'success': False,
                        'message': error_msg,
                        'consecutive_days': 0,
                        'points_earned': 0,
                        'total_points': 0
                    }
                
                # 签到成功，重新获取状态
                time.sleep(2)
                new_status = self.get_mission_status()
                
                if new_status:
                    if new_status.get('already_checked') or new_status.get('points_earned', 0) > 0:
                        log_info("签到成功！")
                        return {
                            'success': True,
                            'message': '签到成功',
                            'consecutive_days': new_status.get('consecutive_days', 0),
                            'points_earned': new_status.get('points_earned', 0),
                            'total_points': new_status.get('total_points', 0)
                        }
                
                # 尝试从签到响应中解析
                mission_data = data.get('mission', {})
                if mission_data:
                    today_credit = mission_data.get('credit', 0)
                    if today_credit > 0:
                        return {
                            'success': True,
                            'message': '签到成功',
                            'consecutive_days': int(mission_data.get('tk', {}).get('days', 0)),
                            'points_earned': int(today_credit),
                            'total_points': int(mission_data.get('my_credit', 0))
                        }
                
                # 可能已经签到过了
                log_info("签到请求完成（可能今日已签到）")
                return {
                    'success': True,
                    'message': '签到完成',
                    'consecutive_days': 0,
                    'points_earned': 0,
                    'total_points': 0
                }
            else:
                log_error(f"签到请求失败: {response.status_code}")
                return {
                    'success': False,
                    'message': f'请求失败: HTTP {response.status_code}',
                    'consecutive_days': 0,
                    'points_earned': 0,
                    'total_points': 0
                }
                
        except Exception as e:
            log_error(f"签到异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return {
                'success': False,
                'message': f'异常: {str(e)}',
                'consecutive_days': 0,
                'points_earned': 0,
                'total_points': 0
            }


# ==================== Selenium 模式（备用） ====================

def checkin_selenium(username, password):
    """
    Selenium 模式签到（备用方案）
    
    注意：需要额外安装 selenium 和 Chrome 浏览器
    """
    log_info("使用 Selenium 模式")
    
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        log_error("未安装 selenium，请先安装: pip install selenium webdriver-manager")
        return {
            'success': False,
            'message': '缺少 selenium 依赖',
            'consecutive_days': 0,
            'points_earned': 0,
            'total_points': 0
        }
    
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
        except Exception:
            driver = webdriver.Chrome(options=chrome_options)
        
        driver.implicitly_wait(10)
        
        # 访问签到页面（会自动跳转到登录）
        driver.get(f'{FORUM_BASE}/mission/today')
        time.sleep(5)
        
        wait = WebDriverWait(driver, 15)
        
        # 检查是否在登录页面
        if 'accounts.zwsoft.cn' in driver.current_url:
            log_info("正在登录...")
            
            # 输入用户名
            try:
                username_input = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="Username"], input[type="text"], input[type="tel"]'))
                )
                username_input.clear()
                username_input.send_keys(username)
                log_debug("用户名已输入")
            except Exception as e:
                log_error(f"找不到用户名输入框: {e}")
            
            # 输入密码
            try:
                password_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
                password_input.clear()
                password_input.send_keys(password)
                log_debug("密码已输入")
            except Exception as e:
                log_error(f"找不到密码输入框: {e}")
            
            # 勾选协议复选框
            try:
                checkboxes = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
                for checkbox in checkboxes:
                    try:
                        if not checkbox.is_selected():
                            driver.execute_script("arguments[0].click();", checkbox)
                            time.sleep(0.3)
                    except Exception:
                        pass
                log_debug("协议已勾选")
            except Exception as e:
                log_debug(f"勾选协议出错（可能无需勾选）: {e}")
            
            # 点击登录按钮
            try:
                login_button = wait.until(
                    EC.element_to_be_clickable((By.XPATH, '//a[contains(text(),"登") or contains(text(),"login")]'))
                )
                login_button.click()
                log_debug("登录按钮已点击")
            except Exception:
                try:
                    login_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
                    driver.execute_script("arguments[0].click();", login_button)
                except Exception:
                    try:
                        driver.execute_script("document.querySelector('form').submit();")
                    except Exception:
                        pass
            
            # 等待登录完成（跳转回论坛）
            for i in range(10):
                time.sleep(2)
                if 'forum.zwsoft.cn' in driver.current_url:
                    log_info("登录成功，已跳转回论坛")
                    break
                log_debug(f"等待登录... 当前URL: {driver.current_url[:50]}")
            else:
                log_error("登录超时或失败")
                return {
                    'success': False,
                    'message': '登录失败（可能需要验证码）',
                    'consecutive_days': 0,
                    'points_earned': 0,
                    'total_points': 0
                }
        
        # 确保在签到页面
        if 'mission/today' not in driver.current_url:
            driver.get(f'{FORUM_BASE}/mission/today')
            time.sleep(5)
        
        page_source = driver.page_source
        
        # 检查是否已签到
        if '今日已签到' in page_source or '已签到' in page_source:
            log_info("今日已经签到过了")
            days_match = re.search(r'连续签到[：:]\s*(\d+)\s*天', page_source)
            total_match = re.search(r'我的积分[：:]\s*(\d+)', page_source)
            
            return {
                'success': True,
                'message': '今日已签到',
                'consecutive_days': int(days_match.group(1)) if days_match else 0,
                'points_earned': 0,
                'total_points': int(total_match.group(1)) if total_match else 0
            }
        
        # 查找签到按钮并点击
        try:
            checkin_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "立刻签到") or contains(text(), "立即签到")]'))
            )
            log_info("找到签到按钮，点击签到...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkin_button)
            time.sleep(1)
            checkin_button.click()
            time.sleep(5)
        except Exception as e:
            log_error(f"点击签到按钮失败: {e}")
        
        # 刷新页面检查结果
        driver.refresh()
        time.sleep(3)
        
        page_source = driver.page_source
        
        # 解析结果
        days_match = re.search(r'连续签到[：:]\s*(\d+)\s*天', page_source)
        total_match = re.search(r'我的积分[：:]\s*(\d+)', page_source)
        points_match = re.search(r'获得\s*(\d+)\s*积分', page_source)
        
        success = '今日未签到' not in page_source and ('今日已签到' in page_source or '已签到' in page_source or points_match)
        
        return {
            'success': success,
            'message': '签到成功' if success else '签到失败',
            'consecutive_days': int(days_match.group(1)) if days_match else 0,
            'points_earned': int(points_match.group(1)) if points_match else 0,
            'total_points': int(total_match.group(1)) if total_match else 0
        }
        
    except Exception as e:
        log_error(f"Selenium签到异常: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        return {
            'success': False,
            'message': f'异常: {str(e)}',
            'consecutive_days': 0,
            'points_earned': 0,
            'total_points': 0
        }
    finally:
        if driver:
            driver.quit()


# ==================== 单账号签到入口 ====================

def do_checkin(account, index):
    """
    执行单个账号的签到
    
    Args:
        account: 账号信息字典
        index: 账号序号
    
    Returns:
        dict: 签到结果
    """
    username = account['username']
    password = account['password']
    
    print(f"\n{'='*50}")
    print(f"  账号{index}: {username}")
    print(f"{'='*50}")
    
    if RUN_MODE == 'selenium':
        # 强制使用 Selenium 模式
        result = checkin_selenium(username, password)
    elif RUN_MODE == 'api':
        # 强制使用 API 模式
        api = ZwCheckinAPI(username, password)
        if not api.login():
            log_error("API模式登录失败")
            result = {
                'success': False,
                'message': 'API登录失败',
                'consecutive_days': 0,
                'points_earned': 0,
                'total_points': 0
            }
        else:
            result = api.checkin()
    else:
        # auto 模式：先尝试 API，失败再用 Selenium
        log_info("模式: auto（先尝试API模式）")
        
        if not HAS_RSA:
            log_info("未安装pycryptodome，直接使用Selenium模式")
            result = checkin_selenium(username, password)
        else:
            api = ZwCheckinAPI(username, password)
            
            if api.login():
                log_info("API模式登录成功，执行签到...")
                result = api.checkin()
                if not result['success']:
                    log_info("API模式签到失败，尝试Selenium模式...")
                    result = checkin_selenium(username, password)
            else:
                log_info("API模式登录失败，降级到Selenium模式...")
                result = checkin_selenium(username, password)
    
    # 输出结果
    status = "✅ 成功" if result['success'] else "❌ 失败"
    print(f"\n签到结果: {status}")
    print(f"消息: {result['message']}")
    if result['consecutive_days'] > 0:
        print(f"连续签到: {result['consecutive_days']} 天")
    if result['points_earned'] > 0:
        print(f"今日获得: {result['points_earned']} 积分")
    if result['total_points'] > 0:
        print(f"总积分: {result['total_points']} 积分")
    
    return result


# ==================== 主函数 ====================

def main():
    """主执行函数"""
    start_time = datetime.now()
    
    print(f"\n{'#'*50}")
    print(f"#  中望技术社区自动签到 v3.0.0 (青龙面板版)")
    print(f"#  运行模式: {RUN_MODE}")
    print(f"#  执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*50}")
    
    # 检查RSA库
    if RUN_MODE in ['api', 'auto'] and not HAS_RSA:
        print(f"\n⚠️  提示: 未安装 pycryptodome，API模式将不可用")
        print(f"   安装命令: pip install pycryptodome")
        if RUN_MODE == 'api':
            log_error("API模式需要pycryptodome库")
            sys.exit(1)
    
    # 读取账号
    accounts = get_accounts()
    if not accounts:
        notify("签到失败", "未配置账号或密码，请检查环境变量设置", level=1)
        sys.exit(1)
    
    results = []
    success_count = 0
    fail_count = 0
    
    for i, account in enumerate(accounts, 1):
        result = do_checkin(account, i)
        result['index'] = i
        result['username'] = account['username']
        results.append(result)
        
        if result['success']:
            success_count += 1
        else:
            fail_count += 1
        
        # 账号间延迟
        if i < len(accounts):
            delay = 5
            log_info(f"等待 {delay} 秒后继续下一个账号...")
            time.sleep(delay)
    
    # 汇总结果
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    total_points = sum(r['points_earned'] for r in results)
    
    summary_lines = []
    summary_lines.append(f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    summary_lines.append(f"运行模式: {RUN_MODE}")
    summary_lines.append(f"账号总数: {len(accounts)} 个")
    summary_lines.append(f"成功: {success_count} 个")
    summary_lines.append(f"失败: {fail_count} 个")
    if total_points > 0:
        summary_lines.append(f"今日共获得: {total_points} 积分")
    summary_lines.append(f"耗时: {duration:.1f} 秒")
    summary_lines.append("")
    summary_lines.append("--- 详细结果 ---")
    
    for r in results:
        status = "✅" if r['success'] else "❌"
        line = f"账号{r['index']} ({r['username']}): {status} {r['message']}"
        if r['consecutive_days'] > 0:
            line += f" | 连续{r['consecutive_days']}天"
        if r['points_earned'] > 0:
            line += f" | +{r['points_earned']}积分"
        if r['total_points'] > 0:
            line += f" | 总计{r['total_points']}积分"
        summary_lines.append(line)
    
    summary = "\n".join(summary_lines)
    
    # 发送通知
    if fail_count > 0:
        notify("中望签到 - 有失败账号", summary, level=1)
    elif NOTIFY_LEVEL >= 2:
        notify("中望签到 - 全部成功", summary, level=2)
    else:
        print(f"\n{'='*50}")
        print("  签到完成汇总")
        print(f"{'-'*50}")
        print(summary)
        print(f"{'='*50}\n")
    
    # 如果有失败账号，退出码为1
    if fail_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断执行")
        sys.exit(0)
    except Exception as e:
        error_msg = f"脚本执行异常: {str(e)}"
        log_error(error_msg)
        import traceback
        traceback.print_exc()
        
        if HAS_NOTIFY and NOTIFY_LEVEL >= 1:
            try:
                ql_send("中望签到 - 脚本异常", error_msg)
            except Exception:
                pass
        
        sys.exit(1)
