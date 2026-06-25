# -*- coding: utf-8 -*-
"""
@File         : zw_checkin.py
@Author       : Hayfan-wu
@Date         : 2025-06-25
@Description  : 中望技术社区自动签到脚本（青龙面板版）
@Version      : 2.0.0

环境变量:
  ZWSOFT_USERNAME  - 中望社区账号（手机号/邮箱），多账号用换行或&分隔
  ZWSOFT_PASSWORD  - 中望社区密码，多账号用换行或&分隔（与账号一一对应）
  ZWSOFT_NOTIFY    - 通知级别，0=关闭 1=仅异常 2=全部通知（默认1）
  ZWSOFT_DEBUG     - 调试模式，true/false（默认false）
  ZWSOFT_MODE      - 运行模式，api=纯API模式 selenium=浏览器模式（默认api）

依赖库:
  requests>=2.28.0

cron: 0 0 1 * * *
定时规则：每天凌晨1点执行

使用说明：
  1. 在青龙面板环境变量中添加 ZWSOFT_USERNAME 和 ZWSOFT_PASSWORD
  2. 多账号格式：每行一个账号，密码与账号按顺序一一对应
  3. 推荐使用 API 模式，轻量快速，无需安装浏览器
  4. 如果 API 模式不可用，可切换为 selenium 模式（需额外安装依赖）
"""

import os
import sys
import re
import time
import json
import requests
from datetime import datetime

# ==================== 配置区域 ====================

ENV_USERNAME = 'ZWSOFT_USERNAME'
ENV_PASSWORD = 'ZWSOFT_PASSWORD'
ENV_NOTIFY = 'ZWSOFT_NOTIFY'
ENV_DEBUG = 'ZWSOFT_DEBUG'
ENV_MODE = 'ZWSOFT_MODE'

# 中望社区URL配置
LOGIN_URL = 'https://accounts.zwsoft.cn/connect/token'
CHECKIN_URL = 'https://forum.zwsoft.cn/wp-json/b2/v1/userMission'
USER_MISSION_URL = 'https://forum.zwsoft.cn/wp-json/b2/v1/getUserMission'
USER_GOLD_URL = 'https://forum.zwsoft.cn/wp-json/b2/v1/getUserGoldData'

# 客户端配置（从论坛登录流程中获取）
CLIENT_ID = 'zwforum'
CLIENT_SECRET = 'zwforum.secret'
SCOPE = 'openid profile email phone offline_access ZMS.UserDetails.Read'

# ==================== 通知模块 ====================

try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

NOTIFY_LEVEL = int(os.getenv(ENV_NOTIFY, '1'))
DEBUG = os.getenv(ENV_DEBUG, 'false').lower() == 'true'
RUN_MODE = os.getenv(ENV_MODE, 'api').lower()


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


# ==================== API 模式核心功能 ====================

class ZwCheckinAPI:
    """中望社区签到 - API模式"""
    
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def login(self):
        """
        使用密码模式登录获取Token
        
        Returns:
            bool: 是否登录成功
        """
        log_info(f"正在登录账号: {self.username}")
        
        try:
            data = {
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'grant_type': 'password',
                'username': self.username,
                'password': self.password,
                'scope': SCOPE
            }
            
            log_debug(f"登录请求数据: client_id={CLIENT_ID}, username={self.username}")
            
            response = self.session.post(
                LOGIN_URL,
                data=data,
                timeout=30,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            log_debug(f"登录响应状态码: {response.status_code}")
            log_debug(f"登录响应内容: {response.text[:500]}")
            
            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get('access_token')
                self.refresh_token = result.get('refresh_token')
                
                if self.access_token:
                    log_info("登录成功")
                    return True
                else:
                    log_error("登录响应中未找到 access_token")
                    return False
            else:
                log_error(f"登录失败，状态码: {response.status_code}")
                log_error(f"响应内容: {response.text[:500]}")
                return False
                
        except Exception as e:
            log_error(f"登录异常: {e}")
            return False
    
    def _get_forum_token(self):
        """
        获取论坛JWT Token（通过SSO同步）
        
        Returns:
            str: 论坛JWT Token
        """
        # 尝试使用统一账号Token访问论坛，获取论坛会话
        # 7B2主题通常需要WordPress的登录态
        # 这里我们尝试直接使用统一账号的Token调用论坛API
        # 如果不行，需要额外的SSO同步流程
        
        # 方式1：直接使用Bearer Token调用论坛API
        # 方式2：通过SSO跳转获取WordPress Cookie
        
        # 先尝试直接调用，看是否支持
        return self.access_token
    
    def get_mission_status(self):
        """
        获取签到状态
        
        Returns:
            dict: 签到状态信息
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.post(
                USER_MISSION_URL,
                headers=headers,
                json={},
                timeout=30
            )
            
            log_debug(f"获取签到状态响应: {response.status_code} - {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_mission_data(data)
            else:
                log_error(f"获取签到状态失败: {response.status_code}")
                return None
                
        except Exception as e:
            log_error(f"获取签到状态异常: {e}")
            return None
    
    def _parse_mission_data(self, data):
        """
        解析签到数据
        
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
        
        # 根据7B2主题的标准格式解析
        if isinstance(data, dict):
            # 检查是否有 status 字段
            if data.get('status') == 0 or data.get('success'):
                mission_data = data.get('data', {})
                
                # 连续签到天数
                if 'continuous_days' in mission_data:
                    result['consecutive_days'] = int(mission_data['continuous_days'])
                elif 'continue_days' in mission_data:
                    result['consecutive_days'] = int(mission_data['continue_days'])
                
                # 今日是否已签到
                if 'today_checked' in mission_data:
                    result['already_checked'] = bool(mission_data['today_checked'])
                elif 'is_check' in mission_data:
                    result['already_checked'] = bool(mission_data['is_check'])
                
                # 今日获得积分
                if 'today_gold' in mission_data:
                    result['points_earned'] = int(mission_data['today_gold'])
                elif 'gold_reward' in mission_data:
                    result['points_earned'] = int(mission_data['gold_reward'])
                
                # 总积分
                if 'total_gold' in mission_data:
                    result['total_points'] = int(mission_data['total_gold'])
        
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
                'Authorization': f'Bearer {self.access_token}',
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
                
                # 解析签到结果
                if data.get('status') == 0 or data.get('success'):
                    # 签到成功，重新获取状态
                    time.sleep(2)
                    new_status = self.get_mission_status()
                    
                    if new_status:
                        return {
                            'success': True,
                            'message': '签到成功',
                            'consecutive_days': new_status.get('consecutive_days', 0),
                            'points_earned': new_status.get('points_earned', 0),
                            'total_points': new_status.get('total_points', 0)
                        }
                    else:
                        # 从签到响应中解析
                        result_data = data.get('data', {})
                        return {
                            'success': True,
                            'message': '签到成功',
                            'consecutive_days': int(result_data.get('continuous_days', 0)),
                            'points_earned': int(result_data.get('gold_reward', 0)),
                            'total_points': int(result_data.get('total_gold', 0))
                        }
                else:
                    error_msg = data.get('msg', data.get('message', '签到失败'))
                    log_error(f"签到失败: {error_msg}")
                    return {
                        'success': False,
                        'message': error_msg,
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
        
        # 登录
        driver.get('https://accounts.zwsoft.cn/Account/Login')
        time.sleep(3)
        
        wait = WebDriverWait(driver, 10)
        
        # 输入用户名
        username_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="Username"], input[type="text"], input[type="tel"]'))
        )
        username_input.clear()
        username_input.send_keys(username)
        
        # 输入密码
        password_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
        password_input.clear()
        password_input.send_keys(password)
        
        # 勾选协议
        try:
            checkboxes = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
            for checkbox in checkboxes:
                if not checkbox.is_selected():
                    driver.execute_script("arguments[0].click();", checkbox)
                    time.sleep(0.3)
        except Exception:
            pass
        
        # 点击登录
        try:
            login_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//a[contains(text(),"登") or contains(text(),"login")]'))
            )
            login_button.click()
        except Exception:
            try:
                login_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
                driver.execute_script("arguments[0].click();", login_button)
            except Exception:
                driver.execute_script("document.querySelector('form').submit();")
        
        time.sleep(5)
        
        # 检查登录结果
        if 'accounts.zwsoft.cn' in driver.current_url:
            return {
                'success': False,
                'message': '登录失败（可能需要验证码）',
                'consecutive_days': 0,
                'points_earned': 0,
                'total_points': 0
            }
        
        log_info("登录成功")
        
        # 访问签到页面
        driver.get('https://forum.zwsoft.cn/mission/today')
        time.sleep(5)
        
        page_source = driver.page_source
        
        # 检查是否已签到
        if '今日已签到' in page_source:
            # 解析信息
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
                EC.presence_of_element_located((By.XPATH, '//button[contains(text(), "立刻签到") or contains(text(), "立即签到")]'))
            )
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
        
        success = '今日未签到' not in page_source
        
        return {
            'success': success,
            'message': '签到成功' if success else '签到失败',
            'consecutive_days': int(days_match.group(1)) if days_match else 0,
            'points_earned': int(points_match.group(1)) if points_match else 0,
            'total_points': int(total_match.group(1)) if total_match else 0
        }
        
    except Exception as e:
        log_error(f"Selenium签到异常: {e}")
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
        result = checkin_selenium(username, password)
    else:
        # API 模式
        api = ZwCheckinAPI(username, password)
        
        # 登录
        if not api.login():
            # API模式失败，自动降级到Selenium模式尝试
            log_info("API模式登录失败，尝试Selenium模式...")
            result = checkin_selenium(username, password)
        else:
            # 执行签到
            result = api.checkin()
    
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
    print(f"#  中望技术社区自动签到 v2.0.0 (青龙面板版)")
    print(f"#  运行模式: {RUN_MODE}")
    print(f"#  执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*50}")
    
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
            delay = 3
            log_info(f"等待 {delay} 秒后继续下一个账号...")
            time.sleep(delay)
    
    # 汇总结果
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    total_points = sum(r['points_earned'] for r in results)
    total_gold = sum(r['total_points'] for r in results)
    
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
