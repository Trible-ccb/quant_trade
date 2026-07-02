#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
聚宽模拟策略打通MiniQMT实盘 - 自动化环境部署脚本（已修复转义警告）
适用于Windows Server，建议以管理员权限运行
"""

import os
import sys
import subprocess
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

# ---------- 配置项（可修改） ----------
QMT_USERDATA_DIR = r"C:\QMT\userdata_mini"   # QMT用户数据目录，请根据实际修改
QMT_ACCOUNT_ID = ""                          # 证券资金账号
QMT_SERVER_TOKEN = ""                        # 自定义token

PROJECT_DIR = Path(r"C:\qmt_trade")          # 项目主目录
PYTHON_VERSION = "3.12.10"                   # 固定版本
SERVER_PORT = 58620                          # 服务端口
# ---------------------------------------

def print_step(msg):
    print("\n" + "="*60)
    print(f"▶ {msg}")
    print("="*60)

def run_cmd(cmd, cwd=None, capture=False, check=True):
    """执行命令，返回输出"""
    print(f"执行命令: {cmd}")
    if cwd:
        print(f"工作目录: {cwd}")
    if capture:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        if check and result.returncode != 0:
            print("命令执行失败，错误信息：")
            print(result.stderr)
            sys.exit(result.returncode)
        return result.stdout.strip()
    else:
        result = subprocess.run(cmd, shell=True, cwd=cwd)
        if check and result.returncode != 0:
            sys.exit(result.returncode)
        return ""

def check_python():
    """检查Python是否安装，若不存在则自动下载并安装"""
    try:
        output = run_cmd("python --version", capture=True)
        print(f"已安装: {output}")
        if "3.12" in output:
            return True
        else:
            print("当前Python版本不是3.12，建议使用3.12。继续使用当前版本（可能存在兼容性问题）")
            return True
    except:
        print("未找到Python，开始自动安装Python 3.12...")
        install_python()
        return True

def install_python():
    """下载并静默安装Python 3.12"""
    download_url = f"https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/all/EHHnbqNS9owe9lxoDt6czfNQnjh/?mount_node_token=PVjPd0pDaoCioUxjF8VcuH0Lntg&mount_point=docx_file"
    installer_path = Path(tempfile.gettempdir()) / f"python-3.12.10-amd64.exe"
    print(f"正在下载Python安装程序: {download_url}")
    urllib.request.urlretrieve(download_url, installer_path)
    print("下载完成，开始静默安装（将自动添加到PATH）...")
    run_cmd(f'"{installer_path}" /quiet InstallAllUsers=1 PrependPath=1')
    print("Python安装完成，请重启脚本或手动刷新环境变量")
    installer_path.unlink(missing_ok=True)
    sys.exit("请重新打开命令行（或重启服务器）后再次运行脚本以继续。")

def create_project_dir():
    """创建项目目录"""
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"项目目录已创建: {PROJECT_DIR}")
    return PROJECT_DIR

def create_virtual_env():
    """在项目目录下创建虚拟环境"""
    venv_path = PROJECT_DIR / ".venv"
    if venv_path.exists():
        print("虚拟环境已存在，跳过创建。")
        return venv_path
    print("创建虚拟环境...")
    run_cmd(f"python -m venv {venv_path}", cwd=PROJECT_DIR)
    print("虚拟环境创建成功")
    return venv_path

def install_dependencies(venv_path):
    """在虚拟环境中安装bullet-trade"""
    pip_exe = venv_path / "Scripts" / "pip.exe"
    python_exe = venv_path / "Scripts" / "python.exe"
    # 升级pip
    print("升级pip...")
    run_cmd(f'"{python_exe}" -m pip install --upgrade pip', cwd=PROJECT_DIR)
    # 配置清华镜像
    print("配置pip镜像源...")
    run_cmd(f'"{pip_exe}" config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple', cwd=PROJECT_DIR)
    run_cmd(f'"{pip_exe}" config set global.trusted-host pypi.tuna.tsinghua.edu.cn', cwd=PROJECT_DIR)
    # 安装bullet-trade[qmt]
    print("安装 bullet-trade[qmt]...")
    run_cmd(f'"{pip_exe}" install "bullet-trade[qmt]"', cwd=PROJECT_DIR)
    print("依赖安装完成")

def create_env_file():
    """生成.env配置文件"""
    env_path = PROJECT_DIR / ".env"
    if env_path.exists():
        print(".env文件已存在，覆盖前请确认。是否覆盖？(y/n)")
        if input().strip().lower() != 'y':
            print("保留现有.env文件")
            return
    qmt_data = input(f"请输入QMT用户数据目录（默认: {QMT_USERDATA_DIR}）: ").strip() or QMT_USERDATA_DIR
    account = input(f"请输入证券资金账号（默认: {QMT_ACCOUNT_ID or '空'}）: ").strip() or QMT_ACCOUNT_ID
    token = input("请输入QMT_SERVER_TOKEN（自定义密码，留空则随机生成）: ").strip()
    if not token:
        import secrets
        token = secrets.token_hex(8)
        print(f"随机生成token: {token}")

    content = f"""QMT_DATA_PATH={qmt_data}
QMT_ACCOUNT_ID={account}
QMT_SERVER_TOKEN={token}
"""
    env_path.write_text(content, encoding='utf-8')
    print(f".env文件已生成: {env_path}")
    return env_path

def create_start_script():
    """生成启动服务的bat脚本（已修复转义警告）"""
    bat_path = PROJECT_DIR / "start_server.bat"
    # 使用双反斜杠 \\ 来转义，避免 Python 将 \. 或 \S 视为无效转义序列
    # 在写入 .bat 文件后，\\ 会被还原为单个 \，路径完全正确
    content = f"""@echo off
echo 激活虚拟环境...
call "{PROJECT_DIR}\\.venv\\Scripts\\activate"
echo 启动 bullet-trade 服务...
bullet-trade --env-file .env server --listen 0.0.0.0 --port {SERVER_PORT} --enable-data --enable-broker
pause
"""
    bat_path.write_text(content, encoding='gbk')
    print(f"启动脚本已生成: {bat_path}")
    print("您可以直接双击 start_server.bat 启动服务。")

def add_firewall_rule():
    """自动添加防火墙入站规则（需要管理员权限）"""
    try:
        run_cmd(f'netsh advfirewall firewall add rule name="QMT_Trade" dir=in action=allow protocol=TCP localport={SERVER_PORT}', check=False)
        print(f"防火墙已开放端口 {SERVER_PORT}（如果之前存在相同规则可能报错，忽略即可）")
    except:
        print("添加防火墙规则失败，请手动在安全组/防火墙中开放端口", SERVER_PORT)

def main():
    print("""
╔═══════════════════════════════════════════════════════╗
║  聚宽模拟策略打通MiniQMT实盘 - 自动化部署脚本         ║
║  请确保已登录QMT客户端（独立交易模式）                ║
║  并确保已下载Python包（首次需非独立模式登录下载）      ║
╚═══════════════════════════════════════════════════════╝
    """)

    print_step("检查Python环境")
    check_python()

    print_step("创建项目目录")
    create_project_dir()

    print_step("创建虚拟环境")
    venv_path = create_virtual_env()

    print_step("安装依赖 (bullet-trade)")
    install_dependencies(venv_path)

    print_step("生成.env配置文件")
    create_env_file()

    print_step("生成启动脚本")
    create_start_script()

    print_step("配置防火墙")
    add_firewall_rule()

    print_step("部署完成！")
    print("接下来请手动执行以下步骤：")
    print("1. 确保QMT客户端已登录（独立交易模式）")
    print("2. 双击运行 start_server.bat 启动服务")
    print("3. 在聚宽研究环境上传 wrapper 和 helper 文件，并修改IP、token")
    print("4. 运行测试脚本验证连通性")
    print(f"\n服务启动命令（手动）：")
    print(f"cd {PROJECT_DIR}")
    print(f".venv\\Scripts\\activate")
    print(f"bullet-trade --env-file .env server --listen 0.0.0.0 --port {SERVER_PORT} --enable-data --enable-broker")
    print("\n祝交易顺利！")

if __name__ == "__main__":
    main()