"""pytest 共享配置：把 scripts/ 加到 sys.path，方便 `from lib import ...`"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# fixtures/ 是 Spike-1/2/3 各语言的样本项目，自身含 *_test.* 文件，
# 不能让 pytest collect 进当前测试套件
collect_ignore_glob = ["fixtures/*", "fixtures/**/*"]
