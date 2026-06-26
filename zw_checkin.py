# -*- coding: utf-8 -*-
"""
@File         : zw_checkin.py
@Author       : Hayfan-wu
@Date         : 2025-06-25
@Description  : 中望技术社区自动签到脚本（青龙面板版）
@Version      : 4.0.0

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
AUTHORIZE_URL = 'https://accounts.zwsoft.cn/connect/authorize'
PUBKEY_URL = 'https://accounts.zwsoft.cn/Common/Getpubkeys'
FORUM_BASE = 'https://forum.zwsoft.cn'
FORUM_REST = f'{FORUM_BASE}/wp-json/b2/v1'
CHECKIN_URL = f'{FORUM_REST}/userMission'
USER_MISSION_URL = f'{FORUM_REST}/getUserMission'
LOGIN_CALLBACK = f'{FORUM_BASE}/wp-content/themes/zwforumchild/login.php'

# 客户端配置
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


# ==================== 工具函数 ====================

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


def rsa_encrypt(public_key_pem, plaintext):
    """
    RSA加密，与JSEncrypt兼容（PKCS1_v1_5填充）
    
    Args:
        public_key_pem: 公钥（PEM格式或裸base64）
        plaintext: 要加密的明文
    
    Returns:
        str: base64编码的密文
    """
    if not public_key_pem.startswith('-----BEGIN'):
        public_key_pem = f'-----BEGIN PUBLIC KEY-----\n{public_key_pem}\n-----END PUBLIC KEY-----'
    
    public_key = RSA.import_key(public_key_pem)
    cipher = PKCS1_v1_5.new(public_key)
    
    # 分段加密（JSEncrypt使用117字节的块大小）
    max_block_size = 117
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
    """中望社区签到 - API模式（模拟浏览器表单提交）
    
    登录流程：
    1. 访问论坛首页
    2. 发起OAuth2授权请求（带PKCE参数），跳转到IdentityServer登录页
    3. 获取RSA公钥，加密密码
    4. 普通表单POST提交登录
    5. 跟随所有重定向回到论坛
    6. 验证登录状态
    """
    
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.b2_token = None  # 论坛JWT token 或 '__cookie_mode__'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.code_verifier = None
        self.code_challenge = None
        self.state = None
        self.public_key = None
    
    def _get_public_key(self):
        """获取RSA公钥"""
        log_debug("获取RSA公钥...")
        try:
            response = self.session.get(PUBKEY_URL, timeout=30)
            if response.status_code == 200:
                key = response.text.strip().strip('"')
                self.public_key = key
                log_debug(f"公钥获取成功: {key[:50]}...")
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
                    'Content-Type': 'application/json'
                }
                response = self.session.post(
                    USER_MISSION_URL, headers=headers, json={}, timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    mission = data.get('mission', {})
                    if mission.get('current_user', 0) > 0:
                        self.b2_token = b2_token_cookie
                        log_info("登录成功（b2_token cookie有效）")
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
        模拟浏览器登录（表单提交方式）
        
        Returns:
            bool: 是否登录成功
        """
        log_info(f"正在登录账号: {self.username}")
        
        if not HAS_RSA:
            log_error("未安装pycryptodome，无法使用API模式登录")
            log_error("请安装: pip install pycryptodome")
            return False
        
        try:
            # 步骤1：访问论坛首页，建立会话
            log_debug("步骤1：访问论坛首页...")
            self.session.get(FORUM_BASE, timeout=30)
            log_debug(f"当前Cookies: {list(self.session.cookies.keys())}")
            
            # 步骤2：生成PKCE参数，发起授权请求
            log_debug("步骤2：发起OAuth2授权请求...")
            self.code_verifier = generate_code_verifier()
            self.code_challenge = generate_code_challenge(self.code_verifier)
            self.state = generate_state()
            
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
            
            login_page_resp = self.session.get(auth_url, allow_redirects=True, timeout=30)
            log_debug(f"登录页URL: {login_page_resp.url[:100]}...")
            log_debug(f"登录页状态码: {login_page_resp.status_code}")
            
            # 检查是否已经登录了（直接跳转到回调）
            if 'zwforumchild/login.php' in login_page_resp.url:
                log_debug("已登录状态，直接验证...")
                if self._verify_login():
                    return True
            
            # 步骤3：获取RSA公钥
            log_debug("步骤3：获取RSA公钥...")
            if not self._get_public_key():
                return False
            
            # 步骤4：从登录页提取表单参数
            log_debug("步骤4：提取登录页表单参数...")
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
            client_id = client_match.group(1) if client_match else CLIENT_ID
            
            log_debug(f"RequestVerificationToken: {request_token[:20]}..." if request_token else "未找到RequestVerificationToken")
            log_debug(f"ReturnUrl: {return_url[:50]}..." if return_url else "未找到ReturnUrl")
            log_debug(f"ClientId: {client_id}")
            
            if not request_token:
                log_error("未能从登录页面提取到RequestVerificationToken")
                return False
            
            # 步骤5：加密密码
            log_debug("步骤5：加密密码...")
            encrypted_password = rsa_encrypt(self.public_key, self.password)
            log_debug(f"密码加密成功: {encrypted_password[:20]}...")
            
            # 步骤6：表单提交登录
            log_debug("步骤6：提交登录表单...")
            
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
                'button': 'login'
            }
            
            # 查找页面中的checkbox，全部勾选
            checkbox_matches = re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"', page_html)
            for cb_name in checkbox_matches:
                login_data[cb_name] = 'on'
            
            log_debug(f"提交登录到: {login_page_resp.url[:80]}...")
            
            login_resp = self.session.post(
                login_page_resp.url,
                data=login_data,
                allow_redirects=True,
                timeout=30
            )
            
            log_debug(f"最终URL: {login_resp.url[:100]}...")
            log_debug(f"状态码: {login_resp.status_code}")
            log_debug(f"Cookies: {list(self.session.cookies.keys())}")
            
            # 检查是否还在登录页（登录失败）
            if 'Account/Login' in login_resp.url:
                log_error("登录失败：仍在登录页面")
                # 尝试提取错误信息
                error_match = re.search(r'class="[^"]*error[^"]*"[^>]*>([^<]+)', login_resp.text)
                if error_match:
                    log_error(f"错误信息: {error_match.group(1).strip()}")
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
                'Content-Type': 'application/json',
                'Referer': FORUM_BASE + '/'
            }
            
            # 如果有b2_token（不是cookie模式），添加Authorization头
            if self.b2_token and self.b2_token != '__cookie_mode__':
                headers['Authorization'] = f'Bearer {self.b2_token}'
            
            response = self.session.post(
                USER_MISSION_URL,
                headers=headers,
                json={},
                timeout=30
            )
            
            log_debug(f"获取签到状态响应: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                mission = data.get('mission', {})
                
                # 解析签到状态
                already_checked = mission.get('user_mission', {}).get('is_complete', False)
                consecutive_days = mission.get('user_mission', {}).get('continuous_day', 0)
                total_points = mission.get('my_credit', 0)
                points_earned = mission.get('user_mission', {}).get('credit', 0)
                
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
            
            # 执行签到
            headers = {
                'Content-Type': 'application/json',
                'Referer': FORUM_BASE + '/'
            }
            
            # 如果有b2_token（不是cookie模式），添加Authorization头
            if self.b2_token and self.b2_token != '__cookie_mode__':
                headers['Authorization'] = f'Bearer {self.b2_token}'
            
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
                
                # 签到成功
                log_info("签到成功！")
                
                # 重新获取状态
                new_status = self.get_mission_status()
                if new_status:
                    return {
                        'success': True,
                        'message': '签到成功',
                        'consecutive_days': new_status.get('consecutive_days', 0),
                        'points_earned': new_status.get('points_earned', 0),
                        'total_points': new_status.get('total_points', 0)
                    }
                
                return {
                    'success': True,
                    'message': '签到成功',
                    'consecutive_days': 0,
                    'points_earned': 0,
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
        
        # 访问论坛首页
        log_info("访问论坛首页...")
        driver.get(FORUM_BASE)
        time.sleep(3)
        
        # 点击登录按钮
        log_info("点击登录按钮...")
        try:
            login_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//a[contains(text(), "登录") or contains(@class, "login")]'))
            )
            login_btn.click()
        except:
            # 尝试其他选择器
            try:
                login_btn = driver.find_element(By.CSS_SELECTOR, '.signin-btn, .login-btn, [class*="login"]')
                login_btn.click()
            except:
                log_error("未找到登录按钮")
                return {
                    'success': False,
                    'message': '未找到登录按钮',
                    'consecutive_days': 0,
                    'points_earned': 0,
                    'total_points': 0
                }
        
        time.sleep(3)
        
        # 切换到新窗口（如果有）
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
        
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
        for i in range(10):
            if FORUM_BASE in driver.current_url:
                log_info("已跳转到论坛")
                break
            time.sleep(2)
        
        # 切换回主窗口
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[0])
        
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
    print(f"#  中望技术社区自动签到 v4.0.0 (青龙面板版)")
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
        content += f"成功: {success_count} 个\n"
        content += f"失败: {fail_count} 个\n\n"
        
        for item in results:
            status = "✅" if item['result'].get('success') else "❌"
            content += f"{status} {item['username']}: {item['result'].get('message', '')}\n"
        
        notify(title, content, level=1)
    elif NOTIFY_LEVEL >= 2:
        # 全部成功，且通知级别>=2，发送成功通知
        title = f"✅ 中望签到 - 全部成功"
        content = f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"成功: {success_count} 个\n"
        content += f"耗时: {duration:.1f} 秒\n\n"
        
        for item in results:
            r = item['result']
            content += f"✅ {item['username']}: 连续{r.get('consecutive_days', 0)}天, 总积分{r.get('total_points', 0)}\n"
        
        notify(title, content, level=2)


if __name__ == '__main__':
    main()
