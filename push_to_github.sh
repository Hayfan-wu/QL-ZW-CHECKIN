#!/bin/bash
# 推送到 GitHub 仓库脚本

echo "========================================"
echo "  推送到 GitHub 仓库"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "正在检查远程仓库..."
git remote -v

echo ""
echo "正在推送到 GitHub..."
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "  推送成功！"
    echo "  仓库地址: https://github.com/Hayfan-wu/QL-ZW-CHECKIN"
    echo "========================================"
else
    echo ""
    echo "========================================"
    echo "  推送失败"
    echo "========================================"
    echo ""
    echo "请按以下步骤操作："
    echo "1. 确保已登录 GitHub 账号"
    echo "2. 提示输入 GitHub 用户名和 Personal Access Token"
    echo "3. 或者使用 SSH 方式推送"
    echo ""
    echo "手动推送命令："
    echo "  git push -u origin main"
    echo ""
fi
