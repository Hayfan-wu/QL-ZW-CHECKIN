# -*- coding: utf-8 -*-
"""
@File         : zw_checkin.py
@Author       : Hayfan-wu
@Date         : 2025-06-25
@Description  : 中望技术社区自动签到脚本（青龙面板版）
@Version      : 6.2.0

环境变量:
  ZWSOFT_USERNAME     - 中望社区账号（手机号/邮箱），多账号用换行或&分隔
  ZWSOFT_PASSWORD     - 中望社区密码，多账号用换行或&分隔（与账号一一对应）
  ZWSOFT_NOTIFY       - 通知级别，0=关闭 1=仅异常 2=全部通知（默认1）
  ZWSOFT_DEBUG        - 调试模式，true/false（默认false）
  ZWSOFT_MODE         - 运行模式，api=纯API模式 selenium=浏览器模式 auto=自动尝试（默认auto）
  WXPUSHER_APP_TOKEN  - WXPusher应用Token（可选，用于微信推送）
  WXPUSHER_UIDS       - WXPusher接收者UID，多个用逗号分隔（可选）

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

更新日志 v6.2.0:
  - 新增 WXPusher 微信推送支持（配置 WXPUSHER_APP_TOKEN 和 WXPUSHER_UIDS）
  - 优化通知格式，与用户期望的展示样式一致
  - 新增账号脱敏显示（保护隐私）
  - 通知内容展示签到后的实际数据（连续天数、积分等）

更新日志 v6.1.0:
  - 修复签到接口请求格式，改为 form-urlencoded 与前端一致
  - 修复签到状态判断逻辑，使用 credit 字段判断是否已签到
  - 修复签到响应解析，兼容字符串和 JSON 两种返回格式
  - 优化连续签到天数读取（从 tk.days 字段获取）

更新日志 v6.0.0:
  - 重大修复：登录流程完全重构，解决了两种模式都报错的问题
  - 核心发现：PKCE参数必须由论坛生成，不能自己构造授权URL
  - 正确入口：从论坛 login.php 发起授权（它会自己生成 code_verifier）
  - 登录方式：AJAX POST 到 /Account/UserLogin，JSON响应 status=1 表示成功
  - 回调处理：登录成功后跟随重定向，login.php 自动用 code 换 token
  - 验证方式：b2_token cookie + Authorization Bearer 头，current_user > 0 表示登录成功
  - 大幅提升登录成功率

更新日志 v5.0.0:
  - 修复核心登录逻辑：从普通表单提交改为AJAX方式提交到 /Account/UserLogin
  - 正确处理登录响应：JSON格式返回，status=1表示成功，msg为重定向URL
  - 增加AJAX请求头：X-Requested-With、正确的Content-Type
  - 优化登录流程，更贴近真实浏览器行为

更新日志 v4.0.0:
  - 完全重构登录逻辑，采用模拟浏览器表单提交方式
  - 简化流程：从论坛首页→授权→登录表单提交→跟随重定向→验证登录
  - PKCE参数与登录流程一致，避免token无效问题
  - 统一登录验证机制，确保真的登录成功
  - 优化代码结构，提高可维护性
"""

import os
import sys
import re
import time
import json
import base64
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

# WXPusher 推送配置
ENV_WXPUSHER_APP_TOKEN = 'WXPUSHER_APP_TOKEN'
ENV_WXPUSHER_UIDS = 'WXPUSHER_UIDS'

# 中望社区URL配置
PUBKEY_URL = 'https://accounts.zwsoft.cn/Common/Getpubkeys'
FORUM_BASE = 'https://forum.zwsoft.cn'
FORUM_REST = f'{FORUM_BASE}/wp-json/b2/v1'
CHECKIN_URL = f'{FORUM_REST}/userMission'
USER_MISSION_URL = f'{FORUM_REST}/getUserMission'
LOGIN_PHP = f'{FORUM_BASE}/wp-content/themes/zwforumchild/login.php'
LOGIN_API = 'https://accounts.zwsoft.cn/Account/UserLogin'
ACCOUNTS_BASE = 'https://accounts.zwsoft.cn'

# ==================== 通知模块 ====================

try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

NOTIFY_LEVEL = int(os.getenv(ENV_NOTIFY, '1'))
DEBUG = os.getenv(ENV_DEBUG, 'false').lower() == 'true'
RUN_MODE = os.getenv(ENV_MODE, 'auto').lower()

# WXPusher 配置
WXPUSHER_APP_TOKEN = os.getenv(ENV_WXPUSHER_APP_TOKEN, '').strip()
WXPUSHER_UIDS = os.getenv(ENV_WXPUSHER_UIDS, '').strip()
HAS_WXPUSHER = bool(WXPUSHER_APP_TOKEN and WXPUSHER_UIDS)


def wxpusher_push(title, content):
    """
    使用WXPusher推送消息
    
    Args:
        title: 消息标题
        content: 消息内容（支持HTML）
    
    Returns:
        bool: 是否推送成功
    """
    if not HAS_WXPUSHER:
        return False
    
    try:
        # 解析UID列表（支持逗号、换行、空格分隔）
        import re
        uids = [uid.strip() for uid in re.split(r'[,，\n\s]+', WXPUSHER_UIDS) if uid.strip()]
        
        if not uids:
            log_error("WXPusher UID列表为空")
            return False
        
        url = 'https://wxpusher.zjiecode.com/api/send/message'
        
        # 构建HTML内容
        html_content = f"<h3>{title}</h3>\n"
        html_content += content.replace('\n', '<br/>\n')
        
        data = {
            'appToken': WXPUSHER_APP_TOKEN,
            'content': html_content,
            'contentType': 2,  # 2=HTML
            'uids': uids,
        }
        
        resp = requests.post(url, json=data, timeout=30)
        result = resp.json()
        
        if result.get('code') == 1000:
            log_debug(f"WXPusher推送成功")
            return True
        else:
            log_error(f"WXPusher推送失败: {result.get('msg', '未知错误')}")
            return False
            
    except Exception as e:
        log_error(f"WXPusher推送异常: {e}")
        return False


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


def mask_username(username):
    """
    脱敏显示用户名/手机号
    
    Args:
        username: 原始用户名
    
    Returns:
        str: 脱敏后的用户名
    """
    if not username:
        return '***'
    
    # 手机号脱敏
    if len(username) == 11 and username.isdigit():
        return username[:3] + '****' + username[7:]
    
    # 邮箱脱敏
    if '@' in username:
        name, domain = username.split('@', 1)
        if len(name) <= 2:
            return name[0] + '***@' + domain
        else:
            return name[:2] + '***@' + domain
    
    # 其他情况，中间脱敏
    if len(username) <= 2:
        return username + '***'
    else:
        return username[:1] + '****' + username[-1:]


def notify(title, content, level=1):
    """
    发送通知（青龙通知 + WXPusher）
    
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
    
    if NOTIFY_LEVEL >= level:
        # 青龙面板通知
        if HAS_NOTIFY:
            try:
                ql_send(title, content)
            except Exception as e:
                log_error(f"青龙通知失败: {e}")
        
        # WXPusher 推送
        if HAS_WXPUSHER:
            try:
                wxpusher_push(title, content)
            except Exception as e:
                log_error(f"WXPusher推送失败: {e}")


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


# ==================== 工具函数 ====================

def rsa_encrypt(public_key_str, plaintext):
    """
    RSA加密，与JSEncrypt兼容（PKCS1_v1_5填充）
    
    Args:
        public_key_str: 公钥字符串（PEM格式，从JSON解析后）
        plaintext: 要加密的明文
    
    Returns:
        str: base64编码的密文
    """
    # 提取base64部分
    match = re.search(r'-----BEGIN PUBLIC KEY-----(.+?)-----END PUBLIC KEY-----', 
                     public_key_str, re.DOTALL)
    if match:
        b64part = match.group(1).replace('\r', '').replace('\n', '').strip()
    else:
        b64part = public_key_str.strip()
    
    # 解码为DER格式导入
    der_bytes = base64.b64decode(b64part)
    public_key = RSA.import_key(der_bytes)
    
    cipher = PKCS1_v1_5.new(public_key)
    max_block_size = 117  # 2048位密钥 = 256字节, PKCS1_v1_5填充占11字节
    plaintext_bytes = plaintext.encode('utf-8')
    
    encrypted_blocks = []
    for i in range(0, len(plaintext_bytes), max_block_size):
        block = plaintext_bytes[i:i + max_block_size]
        encrypted_block = cipher.encrypt(block)
        encrypted_blocks.append(encrypted_block)
    
    encrypted_data = b''.join(encrypted_blocks)
    return base64.b64encode(encrypted_data).decode('ascii')


# ==================== API 模式核心类 ====================

class ZwCheckinAPI:
    """中望社区签到 - API模式（模拟浏览器AJAX登录）
    
    登录流程（v6.0 正确流程）：
    1. 访问论坛 login.php，触发授权重定向（论坛自己生成PKCE参数）
    2. 获取RSA公钥，加密密码
    3. AJAX POST 到 /Account/UserLogin 提交登录
    4. 登录成功返回 JSON {status:1, msg: 授权回调URL（相对路径）}
    5. 访问授权回调URL，IdentityServer生成code并重定向回论坛login.php
    6. 论坛login.php用code+自己保存的code_verifier换取token
    7. 论坛设置 b2_token 等登录cookie
    8. 验证登录状态（current_user > 0）
    """
    
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.b2_token = None  # 论坛JWT token
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.public_key = None
    
    def _get_public_key(self):
        """获取RSA公钥"""
        log_debug("获取RSA公钥...")
        try:
            response = self.session.get(PUBKEY_URL, timeout=30)
            if response.status_code == 200:
                # 接口返回的是JSON字符串
                try:
                    key = response.json()
                except:
                    key = response.text.strip().strip('"')
                self.public_key = key
                log_debug(f"公钥获取成功")
                return True
            log_error(f"获取公钥失败: HTTP {response.status_code}")
            return False
        except Exception as e:
            log_error(f"获取公钥异常: {e}")
            return False
    
    def _verify_login(self):
        """
        验证登录状态
        
        Returns:
            bool: 是否已登录
        """
        log_debug("验证登录状态...")
        
        # 方法1：检查b2_token cookie并验证
        b2_token_cookie = self.session.cookies.get('b2_token')
        if b2_token_cookie:
            log_debug("检测到b2_token cookie，验证有效性...")
            try:
                headers = {
                    'Authorization': f'Bearer {b2_token_cookie}',
                    'Content-Type': 'application/json',
                    'Referer': FORUM_BASE + '/'
                }
                response = self.session.post(
                    USER_MISSION_URL, headers=headers, json={}, timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    mission = data.get('mission', {})
                    if mission.get('current_user', 0) > 0:
                        self.b2_token = b2_token_cookie
                        log_info("登录成功（b2_token有效）")
                        return True
            except Exception as e:
                log_debug(f"b2_token验证异常: {e}")
        
        # 方法2：纯cookie模式（不带Authorization头）
        log_debug("尝试纯cookie模式验证...")
        try:
            headers = {
                'Content-Type': 'application/json',
                'Referer': FORUM_BASE + '/'
            }
            response = self.session.post(
                USER_MISSION_URL, headers=headers, json={}, timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                mission = data.get('mission', {})
                if mission.get('current_user', 0) > 0:
                    self.b2_token = '__cookie_mode__'
                    log_info("登录成功（cookie模式）")
                    return True
                log_debug(f"cookie模式验证失败，current_user={mission.get('current_user', 0)}")
            else:
                log_debug(f"cookie模式验证失败: HTTP {response.status_code}")
        except Exception as e:
            log_debug(f"cookie模式验证异常: {e}")
        
        return False
    
    def login(self):
        """
        模拟浏览器登录（AJAX方式提交，与UserLogin.js一致）
        
        Returns:
            bool: 是否登录成功
        """
        log_info(f"正在登录账号: {self.username}")
        
        if not HAS_RSA:
            log_error("未安装pycryptodome，无法使用API模式登录")
            log_error("请安装: pip install pycryptodome")
            return False
        
        try:
            # 步骤1：访问论坛login.php，触发授权重定向（论坛生成PKCE）
            log_debug("步骤1：访问论坛login.php，触发授权重定向...")
            login_page_resp = self.session.get(LOGIN_PHP, allow_redirects=True, timeout=30)
            log_debug(f"登录页URL: {login_page_resp.url[:100]}...")
            log_debug(f"登录页状态码: {login_page_resp.status_code}")
            
            # 检查是否已经登录了（直接跳转到首页）
            if login_page_resp.url == FORUM_BASE + '/' or login_page_resp.url == FORUM_BASE:
                log_debug("已登录状态，直接验证...")
                if self._verify_login():
                    return True
            
            # 确保在IdentityServer登录页
            if 'accounts.zwsoft.cn' not in login_page_resp.url:
                log_error(f"未重定向到授权服务器，当前URL: {login_page_resp.url[:80]}")
                return False
            
            # 步骤2：获取RSA公钥
            log_debug("步骤2：获取RSA公钥...")
            if not self._get_public_key():
                return False
            
            # 步骤3：从登录页提取表单参数
            log_debug("步骤3：提取登录页表单参数...")
            page_html = login_page_resp.text
            
            token_match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page_html)
            request_token = token_match.group(1) if token_match else ''
            
            return_match = re.search(r'name="ReturnUrl"[^>]*value="([^"]+)"', page_html)
            return_url = return_match.group(1) if return_match else ''
            
            # 也可以从URL中获取returnUrl
            if not return_url:
                parsed = urllib.parse.urlparse(login_page_resp.url)
                query_params = urllib.parse.parse_qs(parsed.query)
                return_url = query_params.get('ReturnUrl', [''])[0]
            
            client_match = re.search(r'name="ClientId"[^>]*value="([^"]+)"', page_html)
            client_id = client_match.group(1) if client_match else 'Client_zw_tech_forum'
            
            log_debug(f"RequestVerificationToken: {'✓' if request_token else '✗'}")
            log_debug(f"ReturnUrl: {return_url[:50]}..." if return_url else "未找到ReturnUrl")
            log_debug(f"ClientId: {client_id}")
            
            if not request_token:
                log_error("未能从登录页面提取到RequestVerificationToken")
                return False
            
            # 步骤4：加密密码
            log_debug("步骤4：加密密码...")
            encrypted_password = rsa_encrypt(self.public_key, self.password)
            log_debug("密码加密成功")
            
            # 步骤5：AJAX方式提交登录（与UserLogin.js一致）
            log_debug("步骤5：AJAX提交登录...")
            
            login_data = {
                'Agreement': 'true',
                'Username': self.username,
                'Password': encrypted_password,
                'ReturnUrl': return_url,
                'RememberLogin': 'false',
                'LoginType': 'Pwd',
                'ClientId': client_id,
                'ActUser': '',
                'ActCorp': '',
                '__RequestVerificationToken': request_token,
            }
            
            # AJAX请求头
            ajax_headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': login_page_resp.url,
                'Accept': 'application/json, text/javascript, */*; q=0.01',
            }
            
            log_debug(f"提交登录到: {LOGIN_API}")
            
            login_resp = self.session.post(
                LOGIN_API,
                data=login_data,
                headers=ajax_headers,
                allow_redirects=False,
                timeout=30
            )
            
            log_debug(f"登录响应状态码: {login_resp.status_code}")
            
            # 解析登录响应（JSON格式）
            try:
                resp_json = login_resp.json()
                status = resp_json.get('status')
                msg = resp_json.get('msg', '')
                
                log_debug(f"登录响应 status: {status}")
                
                if status != 1:
                    log_error(f"登录失败: status={status}, msg={msg}")
                    return False
                
                # 登录成功，msg是授权回调URL（相对路径）
                log_debug("登录API调用成功，处理重定向URL...")
                
                # msg是相对路径，补全域名
                if msg.startswith('/'):
                    redirect_url = ACCOUNTS_BASE + msg
                else:
                    redirect_url = msg
                
                log_debug(f"重定向URL: {redirect_url[:100]}...")
                
                # 步骤6：访问重定向URL，完成OAuth2回调
                log_debug("步骤6：访问重定向URL，完成OAuth2回调...")
                callback_resp = self.session.get(redirect_url, allow_redirects=True, timeout=30)
                
                log_debug(f"回调最终URL: {callback_resp.url[:100]}...")
                log_debug(f"回调状态码: {callback_resp.status_code}")
                log_debug(f"回调后Cookies: {list(self.session.cookies.keys())}")
                
                # 检查b2_token cookie
                b2_token_cookie = self.session.cookies.get('b2_token')
                if b2_token_cookie:
                    log_debug(f"获取到b2_token cookie")
                
            except json.JSONDecodeError:
                log_error(f"登录响应不是JSON格式: {login_resp.text[:200]}")
                return False
            except Exception as e:
                log_error(f"解析登录响应失败: {e}")
                return False
            
            # 步骤7：验证登录状态
            log_debug("步骤7：验证登录状态...")
            if self._verify_login():
                return True
            
            log_error("登录失败：未能验证登录状态")
            return False
            
        except Exception as e:
            log_error(f"登录异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return False
    
    def get_mission_status(self):
        """
        获取签到状态
        
        Returns:
            dict: 签到状态信息
        """
        try:
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': FORUM_BASE + '/mission'
            }
            
            # 如果有b2_token（不是cookie模式），添加Authorization头
            if self.b2_token and self.b2_token != '__cookie_mode__':
                headers['Authorization'] = f'Bearer {self.b2_token}'
            
            response = self.session.post(
                USER_MISSION_URL,
                headers=headers,
                data='count=10&paged=1',
                timeout=30
            )
            
            log_debug(f"获取签到状态响应: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                mission = data.get('mission', {})
                
                # 解析签到状态
                # credit字段有值表示今日已签到（与前端JS逻辑一致）
                credit_val = mission.get('credit', '')
                already_checked = bool(credit_val)
                
                # 连续签到天数
                tk = mission.get('tk', {})
                consecutive_days = tk.get('days', 0) if isinstance(tk, dict) else 0
                
                total_points = mission.get('my_credit', 0)
                points_earned = credit_val if credit_val else 0
                
                return {
                    'already_checked': already_checked,
                    'consecutive_days': consecutive_days,
                    'total_points': total_points,
                    'points_earned': points_earned,
                    'raw': data
                }
            else:
                log_error(f"获取签到状态失败: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            log_error(f"获取签到状态异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return None
    
    def checkin(self):
        """
        执行签到
        
        Returns:
            dict: 签到结果
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
            
            # 执行签到（与前端JS一致，使用form-urlencoded格式）
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': FORUM_BASE + '/mission'
            }
            
            # 如果有b2_token（不是cookie模式），添加Authorization头
            if self.b2_token and self.b2_token != '__cookie_mode__':
                headers['Authorization'] = f'Bearer {self.b2_token}'
            
            response = self.session.post(
                CHECKIN_URL,
                headers=headers,
                data='',
                timeout=30
            )
            
            log_debug(f"签到响应: {response.status_code} - {response.text[:500]}")
            
            if response.status_code == 200:
                # 签到接口可能返回字符串（积分值）或JSON对象
                # 先尝试解析JSON
                points_earned = 0
                try:
                    data = response.json()
                    
                    # 如果是字典，检查是否有错误
                    if isinstance(data, dict):
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
                        
                        # 如果有mission字段，从中提取积分
                        if 'mission' in data:
                            mission = data['mission']
                            points_earned = mission.get('credit', 0)
                    elif isinstance(data, str):
                        # 返回的是字符串形式的积分值
                        points_earned = data
                except (json.JSONDecodeError, ValueError):
                    # 不是JSON，可能是纯文本
                    points_earned = response.text.strip().strip('"')
                
                # 签到成功（200状态码即表示成功）
                log_info(f"签到成功！获得积分: {points_earned}")
                
                # 重新获取状态验证
                new_status = self.get_mission_status()
                if new_status:
                    return {
                        'success': True,
                        'message': '签到成功',
                        'consecutive_days': new_status.get('consecutive_days', 0),
                        'points_earned': new_status.get('points_earned', points_earned),
                        'total_points': new_status.get('total_points', 0)
                    }
                
                return {
                    'success': True,
                    'message': '签到成功',
                    'consecutive_days': 0,
                    'points_earned': points_earned,
                    'total_points': 0
                }
            else:
                log_error(f"签到失败: HTTP {response.status_code}")
                return {
                    'success': False,
                    'message': f'HTTP {response.status_code}',
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
    Selenium模式签到（备用方案）
    
    Args:
        username: 用户名
        password: 密码
    
    Returns:
        dict: 签到结果
    """
    log_info("使用Selenium模式签到...")
    
    driver = None
    
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        log_error("未安装selenium，无法使用Selenium模式")
        log_error("请安装: pip install selenium")
        return {
            'success': False,
            'message': '缺少selenium依赖',
            'consecutive_days': 0,
            'points_earned': 0,
            'total_points': 0
        }
    
    try:
        # 配置Chrome选项
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # 尝试不同的chromedriver路径
        driver = None
        driver_paths = [
            '/usr/bin/chromedriver',
            '/usr/local/bin/chromedriver',
            '/root/.cache/selenium/chromedriver/linux64/150.0.7891.200/chromedriver',
        ]
        
        for driver_path in driver_paths:
            if os.path.exists(driver_path):
                log_debug(f"找到chromedriver: {driver_path}")
                from selenium.webdriver.chrome.service import Service
                driver = webdriver.Chrome(service=Service(driver_path), options=chrome_options)
                break
        
        if driver is None:
            # 尝试自动查找
            log_debug("尝试自动查找chromedriver...")
            driver = webdriver.Chrome(options=chrome_options)
        
        log_info("浏览器启动成功")
        
        # 设置超时
        wait = WebDriverWait(driver, 30)
        
        # 访问论坛登录页
        log_info("访问论坛登录页...")
        driver.get(LOGIN_PHP)
        time.sleep(3)
        
        # 输入用户名密码
        log_info("输入账号密码...")
        
        # 等待用户名输入框
        username_input = wait.until(
            EC.presence_of_element_located((By.ID, 'Username'))
        )
        username_input.clear()
        username_input.send_keys(username)
        
        # 输入密码
        password_input = driver.find_element(By.ID, 'Password')
        password_input.clear()
        password_input.send_keys(password)
        
        # 勾选同意条款
        try:
            agree_checkbox = driver.find_element(By.ID, 'Agreement')
            if not agree_checkbox.is_selected():
                agree_checkbox.click()
        except:
            pass
        
        # 点击登录按钮
        log_info("点击登录...")
        try:
            submit_btn = driver.find_element(By.XPATH, '//button[contains(text(), "登录")]')
            submit_btn.click()
        except:
            # 尝试按回车
            from selenium.webdriver.common.keys import Keys
            password_input.send_keys(Keys.ENTER)
        
        time.sleep(5)
        
        # 等待登录完成，跳转到论坛
        log_info("等待登录完成...")
        for i in range(15):
            if FORUM_BASE in driver.current_url and 'login' not in driver.current_url.lower():
                log_info("已跳转到论坛")
                break
            time.sleep(2)
        
        time.sleep(3)
        
        # 访问签到页面
        log_info("访问签到页面...")
        driver.get(f'{FORUM_BASE}/mission')
        time.sleep(5)
        
        # 点击签到按钮
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
            else:
                log_error("API模式登录失败，尝试Selenium模式...")
                result = checkin_selenium(username, password)
    
    # 输出结果
    if result.get('success'):
        print(f"\n✅ 签到成功！")
        print(f"   连续签到: {result.get('consecutive_days', 0)} 天")
        print(f"   获得积分: {result.get('points_earned', 0)}")
        print(f"   总积分: {result.get('total_points', 0)}")
    else:
        print(f"\n❌ 签到失败")
        print(f"   原因: {result.get('message', '未知错误')}")
    
    return result


# ==================== 主函数 ====================

def main():
    """主函数"""
    start_time = datetime.now()
    
    print(f"\n{'#'*50}")
    print(f"#  中望技术社区自动签到 v6.2.0 (青龙面板版)")
    print(f"#  运行模式: {RUN_MODE}")
    print(f"#  执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*50}")
    
    # 读取账号
    accounts = get_accounts()
    if not accounts:
        notify("签到失败", "未找到账号配置，请检查环境变量", level=1)
        return
    
    # 执行签到
    success_count = 0
    fail_count = 0
    results = []
    
    for i, account in enumerate(accounts, 1):
        result = do_checkin(account, i)
        results.append({
            'username': account['username'],
            'result': result
        })
        
        if result.get('success'):
            success_count += 1
        else:
            fail_count += 1
    
    # 汇总结果
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n{'#'*50}")
    print(f"#  签到完成")
    print(f"#  成功: {success_count} 个")
    print(f"#  失败: {fail_count} 个")
    print(f"#  耗时: {duration:.1f} 秒")
    print(f"{'#'*50}\n")
    
    # 发送通知
    if fail_count > 0:
        # 有失败，发送异常通知
        title = f"⚠️ 中望签到 - {fail_count}个账号失败"
        content = f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"成功: {success_count} 个 | 失败: {fail_count} 个\n"
        content += f"耗时: {duration:.1f} 秒\n\n"
        
        for item in results:
            r = item['result']
            masked_name = mask_username(item['username'])
            if r.get('success'):
                content += f"✅ 签到成功！\n"
                content += f"   账号：{masked_name}\n"
                content += f"   连续签到: {r.get('consecutive_days', 0)} 天\n"
                content += f"   获得积分: {r.get('points_earned', 0)}\n"
                content += f"   总积分: {r.get('total_points', 0)}\n\n"
            else:
                content += f"❌ 签到失败\n"
                content += f"   账号：{masked_name}\n"
                content += f"   原因: {r.get('message', '未知错误')}\n\n"
        
        notify(title, content, level=1)
    elif NOTIFY_LEVEL >= 2:
        # 全部成功，且通知级别>=2，发送成功通知
        title = f"✅ 中望签到 - 全部成功"
        
        content = ""
        for item in results:
            r = item['result']
            masked_name = mask_username(item['username'])
            content += f"✅ 签到成功！\n"
            content += f"   账号：{masked_name}\n"
            content += f"   连续签到: {r.get('consecutive_days', 0)} 天\n"
            content += f"   获得积分: {r.get('points_earned', 0)}\n"
            content += f"   总积分: {r.get('total_points', 0)}\n\n"
        
        content += f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"成功: {success_count} 个 | 耗时: {duration:.1f} 秒"
        
        notify(title, content, level=2)


if __name__ == '__main__':
    main()
