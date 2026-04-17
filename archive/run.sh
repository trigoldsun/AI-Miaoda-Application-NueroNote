#!/bin/bash
# NueroNote 启动脚本
# 支持多种运行模式：开发、测试、生产

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 虚拟环境目录
VENV_DIR="$PROJECT_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Python
check_python() {
    if [ ! -d "$VENV_DIR" ]; then
        log_warning "虚拟环境不存在，创建中..."
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        pip install -q -r "$PROJECT_DIR/nueronote_server/requirements.txt"
        log_success "虚拟环境创建完成"
    else
        source "$VENV_DIR/bin/activate"
    fi
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi
    
    log_info "Python版本: $(python3 --version)"
}

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."
    
    # 检查Flask
    if ! python3 -c "import flask" 2>/dev/null; then
        log_warning "Flask未安装，安装中..."
        pip install flask flask-cors
    fi
    
    # 检查数据库
    if [ ! -f "$PROJECT_DIR/nueronote.db" ]; then
        log_warning "数据库文件不存在，将创建新数据库"
    fi
    
    log_success "依赖检查完成"
}

# 初始化数据库
init_database() {
    log_info "初始化数据库..."
    cd "$PROJECT_DIR/nueronote_server"
    python3 -c "
from database import init_db
init_db()
print('数据库初始化完成')
"
    cd "$PROJECT_DIR"
}

# 运行旧版应用
run_legacy() {
    log_info "启动旧版应用 (app.py)..."
    cd "$PROJECT_DIR/nueronote_server"
    NN_SECRET_KEY="${NN_SECRET_KEY:-dev_secret_key_change_in_production}" \
    NN_JWT_SECRET="${NN_JWT_SECRET:-jwt_secret_change_in_production}" \
    python3 app.py
}

# 运行现代化应用
run_modern() {
    log_info "启动现代化应用 (app_modern.py)..."
    cd "$PROJECT_DIR/nueronote_server"
    NN_SECRET_KEY="${NN_SECRET_KEY:-dev_secret_key_change_in_production}" \
    NN_JWT_SECRET="${NN_JWT_SECRET:-jwt_secret_change_in_production}" \
    python3 app_modern.py
}

# 运行测试
run_tests() {
    log_info "运行测试套件..."
    cd "$PROJECT_DIR"
    
    echo "=== 数据库迁移测试 ==="
    python3 nueronote_server/test_migration.py --db nueronote.db
    
    echo ""
    echo "=== 架构测试 ==="
    python3 test_minimal.py
    
    echo ""
    echo "=== 新架构测试 ==="
    python3 test_new_architecture.py
}

# 显示帮助
show_help() {
    echo "NueroNote 启动脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  legacy        运行旧版应用 (app.py)"
    echo "  modern        运行现代化应用 (app_modern.py) [默认]"
    echo "  test          运行测试套件"
    echo "  init          初始化数据库"
    echo "  check         检查依赖和环境"
    echo "  help          显示此帮助信息"
    echo ""
    echo "环境变量:"
    echo "  NN_SECRET_KEY       应用密钥 (生产环境必须设置)"
    echo "  NN_JWT_SECRET       JWT密钥 (生产环境必须设置)"
    echo "  NN_DB              数据库路径 (默认: nueronote.db)"
    echo ""
    echo "示例:"
    echo "  $0 modern                    # 运行现代化应用"
    echo "  $0 legacy                     # 运行旧版应用"
    echo "  NN_SECRET_KEY=xxx $0 modern # 使用自定义密钥运行"
}

# 主函数
main() {
    MODE="${1:-modern}"
    
    check_python
    check_dependencies
    
    case "$MODE" in
        legacy)
            run_legacy
            ;;
        modern)
            run_modern
            ;;
        test)
            run_tests
            ;;
        init)
            init_database
            ;;
        check)
            check_dependencies
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "未知选项: $MODE"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
