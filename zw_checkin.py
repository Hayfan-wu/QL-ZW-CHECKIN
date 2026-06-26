# -*- coding: utf-8 -*-
"""
@File         : zw_checkin.py
@Author       : Hayfan-wu
@Date         : 2025-06-25
@Description  : 中望技术社区自动签到脚本（青龙面板版）
@Version      : 8.0.0

环境变量:
  ZWSOFT_USERNAME     - 中望社区账号（手机号/邮箱），多账号用换行或&分隔
  ZWSOFT_PASSWORD     - 中望社区密码，多账号用换行或&分隔（与账号一一对应）
  ZWSOFT_NOTIFY       - 通知级别，0=关闭 1=仅异常 2=全部通知（默认1）
  ZWSOFT_DEBUG        - 调试模式，true/false（默认false）
  ZWSOFT_RETRY_COUNT  - 失败重试次数（默认1次，即总共尝试2次）
  ZWSOFT_RETRY_INTERVAL - 重试间隔秒数（默认180秒=3分钟）
  ZWSOFT_QL_NOTIFY    - 是否启用青龙面板通知，true/false（默认：配置WXPusher后自动禁用）
  WXPUSHER_APP_TOKEN  - WXPusher应用Token（可选，用于微信推送）
  WXPUSHER_UIDS       - WXPusher全局接收者UID，多个用逗号分隔（可选，所有账号都推送到这些UID）
  WXPUSHER_USER_MAP   - 账号与UID映射，格式：账号1=UID1,账号2=UID2（可选，不同账号推送到不同微信）

依赖库:
  requests>=2.28.0
  pycryptodome>=3.15.0  (用于RSA密码加密)

cron: 0 0 1 * * *
定时规则：每天凌晨1点执行

使用说明：
  1. 在青龙面板环境变量中添加 ZWSOFT_USERNAME 和 ZWSOFT_PASSWORD
  2. 多账号格式：每行一个账号，密码与账号按顺序一一对应
  3. 签到失败会自动重试，默认间隔3分钟重试1次
  4. 支持 WXPusher 微信推送，配置后自动禁用青龙通知避免重复

更新日志 v8.0.0:
  - 移除 Selenium 模式，统一使用 API 模式（更轻量更稳定）
  - 新增失败重试机制：签到失败后自动重试，默认间隔3分钟重试1次
  - 新增 ZWSOFT_RETRY_COUNT 环境变量：控制重试次数
  - 新增 ZWSOFT_RETRY_INTERVAL 环境变量：控制重试间隔（秒）
  - 简化代码结构，提升可维护性

更新日志 v7.0.0:
  - 重大更新：支持多账号分别推送到不同微信（WXPUSHER_USER_MAP）
  - 智能合并：相同微信（UID）的多个账号会自动合并成一条消息，不会重复推送
  - 灵活配置：支持账号与UID一对一、一对多映射
  - 向后兼容：不配置 USER_MAP 时，保持原有全局UID推送行为
  - 新增 WXPUSHER_USER_MAP 环境变量

更新日志 v6.5.0:
  - 优化 WXPusher 消息列表显示：添加 summary 字段，列表只显示简短标题
  - 消息详情页仍展示完整的签到信息（账号、连续天数、积分等）
  - 优化 HTML 排版，行间距更大更易读

更新日志 v6.4.0:
  - 修复重复推送问题：配置 WXPusher 后自动禁用青龙面板通知，避免同时收到两条相同消息
  - 新增 ZWSOFT_QL_NOTIFY 环境变量，可手动控制是否启用青龙通知（true/false）
  - 默认策略：配置了 WXPusher 则只用 WXPusher 推送，未配置则用青龙通知

更新日志 v6.3.0:
  - 修复连续签到天数显示错误：改为使用 mission.always 字段（前端显示"连续签到：XX天"）
  - 之前错误使用 tk.days 字段，实际 tk.days 是"未签到天数"（用于填坑功能）
  - 增强 WXPusher 推送：添加 SSL 错误自动降级、详细调试日志
  - 优化 WXPusher HTML 通知格式，更美观易读

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
ENV_RETRY_COUNT = 'ZWSOFT_RETRY_COUNT'
ENV_RETRY_INTERVAL = 'ZWSOFT_RETRY_INTERVAL'
ENV_QL_NOTIFY = 'ZWSOFT_QL_NOTIFY'

# WXPusher 推送配置
ENV_WXPUSHER_APP_TOKEN = 'WXPUSHER_APP_TOKEN'
ENV_WXPUSHER_UIDS = 'WXPUSHER_UIDS'
ENV_WXPUSHER_USER_MAP = 'WXPUSHER_USER_MAP'  # 账号与UID映射，格式：账号1=UID1,账号2=UID2

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
    _has_ql_notify_module = True
except ImportError:
    _has_ql_notify_module = False

NOTIFY_LEVEL = int(os.getenv(ENV_NOTIFY, '1'))
DEBUG = os.getenv(ENV_DEBUG, 'false').lower() == 'true'

# 重试配置
RETRY_COUNT = int(os.getenv(ENV_RETRY_COUNT, '1'))  # 失败重试次数（默认1次，即总共尝试2次）
RETRY_INTERVAL = int(os.getenv(ENV_RETRY_INTERVAL, '180'))  # 重试间隔（秒），默认180秒=3分钟

# WXPusher 配置
WXPUSHER_APP_TOKEN = os.getenv(ENV_WXPUSHER_APP_TOKEN, '').strip()
WXPUSHER_UIDS = os.getenv(ENV_WXPUSHER_UIDS, '').strip()
WXPUSHER_USER_MAP = os.getenv(ENV_WXPUSHER_USER_MAP, '').strip()
HAS_WXPUSHER = bool(WXPUSHER_APP_TOKEN and (WXPUSHER_UIDS or WXPUSHER_USER_MAP))

# 解析WXPusher UID列表
def _parse_wxpusher_uids(uids_str):
    """解析UID字符串，返回UID列表"""
    import re
    if not uids_str:
        return []
    return [uid.strip() for uid in re.split(r'[,，\n\s]+', uids_str) if uid.strip()]

# 解析账号-UID映射
def _parse_wxpusher_user_map(map_str):
    """
    解析账号与UID的映射关系
    
    支持格式：
    - 账号1=UID1,账号2=UID2
    - 账号1:UID1;账号2:UID2
    - 每行一个：账号1=UID1\n账号2=UID2
    
    Returns:
        dict: {username: [uid1, uid2, ...]}
    """
    user_map = {}
    if not map_str:
        return user_map
    
    import re
    # 按逗号、分号、换行分割
    entries = re.split(r'[,，;\n]+', map_str)
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        # 支持 = 或 : 分隔
        if '=' in entry:
            parts = entry.split('=', 1)
        elif ':' in entry:
            parts = entry.split(':', 1)
        else:
            continue
        
        username = parts[0].strip()
        uids_str = parts[1].strip()
        if username and uids_str:
            uids = _parse_wxpusher_uids(uids_str)
            if uids:
                user_map[username] = uids
    
    return user_map

# 获取账号对应的UID列表
def get_uids_for_user(username):
    """
    获取指定账号对应的WXPusher UID列表
    
    优先级：
    1. 如果配置了 WXPUSHER_USER_MAP，且账号在映射中，返回映射的UID
    2. 否则返回全局 WXPUSHER_UIDS
    3. 如果都没有配置，返回空列表
    
    Args:
        username: 账号用户名
    
    Returns:
        list: UID列表
    """
    # 先检查用户映射
    user_map = _parse_wxpusher_user_map(WXPUSHER_USER_MAP)
    if username in user_map:
        return user_map[username]
    
    # 返回全局UID
    return _parse_wxpusher_uids(WXPUSHER_UIDS)

# 获取所有需要推送的UID（去重）
def get_all_uids():
    """
    获取所有配置的UID（去重）
    
    Returns:
        list: 所有UID的列表
    """
    all_uids = set()
    
    # 全局UID
    all_uids.update(_parse_wxpusher_uids(WXPUSHER_UIDS))
    
    # 用户映射中的UID
    user_map = _parse_wxpusher_user_map(WXPUSHER_USER_MAP)
    for uids in user_map.values():
        all_uids.update(uids)
    
    return list(all_uids)

# 青龙通知配置：如果已配置 WXPusher，默认禁用青龙通知避免重复推送
# 可以通过 ZWSOFT_QL_NOTIFY=true 强制启用青龙通知
_ql_notify_env = os.getenv(ENV_QL_NOTIFY, '').lower().strip()
if _ql_notify_env == 'true':
    HAS_NOTIFY = _has_ql_notify_module
elif _ql_notify_env == 'false':
    HAS_NOTIFY = False
else:
    # 未显式设置时：如果配置了 WXPusher 则禁用青龙通知，否则启用
    HAS_NOTIFY = _has_ql_notify_module and not HAS_WXPUSHER


def wxpusher_push(title, content, uids=None):
    """
    使用WXPusher推送消息
    
    Args:
        title: 消息标题
        content: 消息内容（支持HTML）
        uids: 指定推送的UID列表，None则使用全部配置的UID
    
    Returns:
        bool: 是否推送成功
    """
    if not HAS_WXPUSHER:
        log_debug("WXPusher未配置，跳过推送")
        return False
    
    try:
        # 如果没有指定UID，使用全部配置的UID
        if uids is None:
            uids = get_all_uids()
        
        if not uids:
            log_error("WXPusher UID列表为空")
            return False
        
        log_debug(f"WXPusher推送，UID数量: {len(uids)}")
        
        url = 'https://wxpusher.zjiecode.com/api/send/message'
        
        # 构建HTML内容（不含标题，标题通过summary字段控制）
        html_content = "<div style='font-size:14px; line-height:1.8;'>\n"
        html_content += f"<b style='font-size:16px;'>{title}</b><br/>\n"
        html_content += "<br/>\n"
        html_content += content.replace('\n', '<br/>\n')
        html_content += "\n</div>"
        
        data = {
            'appToken': WXPUSHER_APP_TOKEN,
            'content': html_content,
            'summary': title,  # 消息摘要/列表显示的标题
            'contentType': 2,  # 2=HTML
            'uids': uids,
        }
        
        log_debug(f"WXPusher请求URL: {url}")
        log_debug(f"WXPusher请求数据: appToken=***, uids={uids}")
        
        # 尝试请求，支持SSL验证失败时跳过
        try:
            resp = requests.post(url, json=data, timeout=30)
        except requests.exceptions.SSLError:
            log_debug("WXPusher SSL验证失败，尝试跳过验证...")
            resp = requests.post(url, json=data, timeout=30, verify=False)
        
        log_debug(f"WXPusher响应状态码: {resp.status_code}")
        log_debug(f"WXPusher响应内容: {resp.text[:200]}")
        
        result = resp.json()
        
        if result.get('code') == 1000:
            log_info("WXPusher推送成功")
            return True
        else:
            log_error(f"WXPusher推送失败: code={result.get('code')}, msg={result.get('msg', '未知错误')}")
            return False
            
    except Exception as e:
        log_error(f"WXPusher推送异常: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
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
                
                # 连续签到天数（前端显示"连续签到：XX天"用的是always字段）
                # tk.days 是"未签到天数"（用于填坑功能）
                consecutive_days = int(mission.get('always', 0)) if mission.get('always') else 0
                
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


# ==================== 单账号签到入口 ====================

def do_checkin(account, index):
    """
    执行单个账号的签到（支持失败重试）
    
    Args:
        account: 账号信息字典
        index: 账号序号
    
    Returns:
        dict: 签到结果
    """
    import time
    
    username = account['username']
    password = account['password']
    
    print(f"\n{'='*50}")
    print(f"  账号{index}: {username}")
    print(f"{'='*50}")
    
    # 总共尝试次数 = 1次初始 + RETRY_COUNT次重试
    max_attempts = RETRY_COUNT + 1
    result = None
    
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n⏳ 第 {attempt} 次尝试（共 {max_attempts} 次）...")
            log_info(f"第 {attempt}/{max_attempts} 次尝试签到")
        
        try:
            api = ZwCheckinAPI(username, password)
            
            if not api.login():
                log_error(f"登录失败（第{attempt}次）")
                result = {
                    'success': False,
                    'message': '登录失败',
                    'consecutive_days': 0,
                    'points_earned': 0,
                    'total_points': 0
                }
            else:
                result = api.checkin()
            
            # 签到成功，跳出重试
            if result.get('success'):
                break
                
        except Exception as e:
            log_error(f"签到异常（第{attempt}次）: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            result = {
                'success': False,
                'message': f'异常: {str(e)}',
                'consecutive_days': 0,
                'points_earned': 0,
                'total_points': 0
            }
        
        # 如果还有重试机会，等待后重试
        if attempt < max_attempts:
            log_info(f"等待 {RETRY_INTERVAL} 秒后重试...")
            print(f"   等待 {RETRY_INTERVAL} 秒后重试...")
            time.sleep(RETRY_INTERVAL)
    
    # 输出结果
    if result.get('success'):
        print(f"\n✅ 签到成功！")
        print(f"   连续签到: {result.get('consecutive_days', 0)} 天")
        print(f"   获得积分: {result.get('points_earned', 0)}")
        print(f"   总积分: {result.get('total_points', 0)}")
    else:
        print(f"\n❌ 签到失败")
        print(f"   原因: {result.get('message', '未知错误')}")
        if max_attempts > 1:
            print(f"   已尝试 {max_attempts} 次")
    
    return result


# ==================== 主函数 ====================

def _build_account_content(item):
    """构建单个账号的签到结果内容"""
    r = item['result']
    masked_name = mask_username(item['username'])
    if r.get('success'):
        content = f"✅ 签到成功！\n"
        content += f"   账号：{masked_name}\n"
        content += f"   连续签到: {r.get('consecutive_days', 0)} 天\n"
        content += f"   获得积分: {r.get('points_earned', 0)}\n"
        content += f"   总积分: {r.get('total_points', 0)}\n"
    else:
        content = f"❌ 签到失败\n"
        content += f"   账号：{masked_name}\n"
        content += f"   原因: {r.get('message', '未知错误')}\n"
    return content


def _send_wxpusher_by_group(results, start_time, success_count, fail_count, duration):
    """
    按UID分组发送WXPusher通知
    
    逻辑：
    1. 遍历每个账号，获取其对应的UID列表
    2. 按UID分组，相同UID的账号合并到同一条消息
    3. 分别发送给每个UID（一条消息包含该UID对应的所有账号结果）
    
    Args:
        results: 签到结果列表
        start_time: 开始时间
        success_count: 成功数量
        fail_count: 失败数量
        duration: 耗时（秒）
    """
    if not HAS_WXPUSHER:
        return
    
    # 按UID分组
    uid_groups = {}  # {uid: [item1, item2, ...]}
    
    for item in results:
        username = item['username']
        uids = get_uids_for_user(username)
        for uid in uids:
            if uid not in uid_groups:
                uid_groups[uid] = []
            uid_groups[uid].append(item)
    
    log_debug(f"WXPusher分组推送：共 {len(uid_groups)} 个UID分组")
    
    # 为每个UID分组发送一条消息
    for uid, group_items in uid_groups.items():
        # 统计该分组的成功/失败数
        group_success = sum(1 for item in group_items if item['result'].get('success'))
        group_fail = len(group_items) - group_success
        
        # 确定标题
        if group_fail > 0:
            title = f"⚠️ 中望签到 - {group_fail}个账号失败"
        else:
            title = f"✅ 中望签到 - 全部成功"
        
        # 构建内容
        content = ""
        for item in group_items:
            content += _build_account_content(item) + "\n"
        
        content += f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"成功: {group_success} 个"
        if group_fail > 0:
            content += f" | 失败: {group_fail} 个"
        content += f" | 耗时: {duration:.1f} 秒"
        
        # 发送
        try:
            wxpusher_push(title, content, uids=[uid])
        except Exception as e:
            log_error(f"WXPusher推送到UID {uid} 失败: {e}")


def main():
    """主函数"""
    start_time = datetime.now()
    
    print(f"\n{'#'*50}")
    print(f"#  中望技术社区自动签到 v8.0.0 (青龙面板版)")
    print(f"#  失败重试: {RETRY_COUNT} 次（间隔 {RETRY_INTERVAL} 秒）")
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
    if fail_count > 0 or NOTIFY_LEVEL >= 2:
        # 构建完整内容（用于青龙通知/调试输出）
        if fail_count > 0:
            title = f"⚠️ 中望签到 - {fail_count}个账号失败"
            level = 1
        else:
            title = f"✅ 中望签到 - 全部成功"
            level = 2
        
        # 构建完整内容
        full_content = ""
        for item in results:
            full_content += _build_account_content(item) + "\n"
        
        full_content += f"执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        full_content += f"成功: {success_count} 个"
        if fail_count > 0:
            full_content += f" | 失败: {fail_count} 个"
        full_content += f" | 耗时: {duration:.1f} 秒"
        
        # 青龙面板通知（完整内容）
        if HAS_NOTIFY and NOTIFY_LEVEL >= level:
            try:
                ql_send(title, full_content)
            except Exception as e:
                log_error(f"青龙通知失败: {e}")
        
        # WXPusher 分组推送（按UID分组，相同微信合并成一条）
        if HAS_WXPUSHER and NOTIFY_LEVEL >= level:
            try:
                _send_wxpusher_by_group(results, start_time, success_count, fail_count, duration)
            except Exception as e:
                log_error(f"WXPusher分组推送失败: {e}")
        
        # 控制台输出
        print(f"\n{'='*50}")
        print(f"📢 {title}")
        print(f"{'-'*50}")
        print(f"{full_content}")
        print(f"{'='*50}\n")


if __name__ == '__main__':
    main()
