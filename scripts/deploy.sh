#!/bin/bash
# NueroNote Deployment Script
# 使用方法: ./deploy.sh [dev|staging|prod] [apply|delete|status|logs|restart]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="${1:-prod}"
ACTION="${2:-apply}"
CONTEXT="${3:-}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查kubectl
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl first."
        exit 1
    fi
}

# 检查kustomize
check_kustomize() {
    if ! command -v kustomize &> /dev/null; then
        log_warn "kustomize not found. Will use kubectl apply -k"
    fi
}

# 部署函数
deploy() {
    local env=$1
    log_info "Deploying to $env environment..."
    
    local overlay_dir="${SCRIPT_DIR}/../kubernetes/overlays/${env}"
    
    if [ ! -d "$overlay_dir" ]; then
        log_error "Overlay directory not found: $overlay_dir"
        exit 1
    fi
    
    cd "$overlay_dir"
    
    if command -v kustomize &> /dev/null; then
        log_info "Using kustomize..."
        kustomize build . | kubectl apply -f -
    else
        log_info "Using kubectl apply -k..."
        kubectl apply -k .
    fi
    
    log_info "Deployment completed for $env"
}

# 状态检查
status() {
    local env=$1
    local namespace="nueronote-${env}"
    
    log_info "Checking status for $env environment..."
    
    echo ""
    echo "=== Deployments ==="
    kubectl get deployments -n "$namespace" 2>/dev/null || echo "No deployments found"
    
    echo ""
    echo "=== Pods ==="
    kubectl get pods -n "$namespace" 2>/dev/null || echo "No pods found"
    
    echo ""
    echo "=== Services ==="
    kubectl get services -n "$namespace" 2>/dev/null || echo "No services found"
    
    echo ""
    echo "=== Ingress ==="
    kubectl get ingress -n "$namespace" 2>/dev/null || echo "No ingress found"
}

# 日志查看
logs() {
    local env=$1
    local namespace="nueronote-${env}"
    local component="${3:-}"
    
    if [ -n "$component" ]; then
        kubectl logs -n "$namespace" -l "app=nueronote,component=${component}" --tail=100 -f
    else
        kubectl logs -n "$namespace" -l "app=nueronote" --tail=100 -f
    fi
}

# 重启
restart() {
    local env=$1
    local namespace="nueronote-${env}"
    local component="${3:-}"
    
    log_info "Restarting deployments in $namespace..."
    
    if [ -n "$component" ]; then
        kubectl rollout restart deployment -n "$namespace" -l "app=nueronote,component=${component}"
    else
        kubectl rollout restart deployment -n "$namespace" -l "app=nueronote"
    fi
    
    kubectl rollout status deployment -n "$namespace" --timeout=300s
    log_info "Restart completed"
}

# 删除
delete() {
    local env=$1
    local overlay_dir="${SCRIPT_DIR}/../kubernetes/overlays/${env}"
    
    log_warn "Deleting resources in $env environment..."
    
    cd "$overlay_dir"
    
    if command -v kustomize &> /dev/null; then
        kustomize build . | kubectl delete -f -
    else
        kubectl delete -k .
    fi
    
    log_info "Deletion completed for $env"
}

# 主函数
main() {
    check_kubectl
    
    case "$ACTION" in
        apply)
            deploy "$NAMESPACE"
            status "$NAMESPACE"
            ;;
        delete)
            delete "$NAMESPACE"
            ;;
        status)
            status "$NAMESPACE"
            ;;
        logs)
            logs "$NAMESPACE"
            ;;
        restart)
            restart "$NAMESPACE"
            ;;
        *)
            echo "Usage: $0 [dev|staging|prod] [apply|delete|status|logs|restart] [context]"
            echo ""
            echo "Examples:"
            echo "  $0 dev apply          # 部署到开发环境"
            echo "  $0 prod status        # 查看生产环境状态"
            echo "  $0 prod logs backend  # 查看后端日志"
            echo "  $0 prod restart       # 重启生产环境所有组件"
            echo "  $0 prod delete        # 删除生产环境资源"
            exit 1
            ;;
    esac
}

main "$@"
