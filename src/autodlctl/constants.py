from __future__ import annotations

import re


DEFAULT_URL = "https://www.autodl.com/console/instance/"
BALANCE_URL = "https://www.autodl.com/console/cost/incomeExpend"
DEFAULT_STORAGE_STATE_PATH = ".autodl/storage_state.json"

START_LABELS = ("开机", "启动", "启动实例", "启动容器", "开始")
STOP_LABELS = ("关机", "停止", "关闭", "停止实例", "销毁")
NO_CARD_START_LABEL = "无卡模式开机"

START_SUCCESS_MARKERS = ("开机中", "运行中")
STOP_SUCCESS_MARKERS = ("关机中", "已关机")

DETAIL_FIELD_KEY_MAP = {
    "镜像": "image",
    "GPU": "gpu",
    "CPU": "cpu",
    "内存": "memory",
    "硬盘": "disk",
    "附加磁盘": "extra_disk",
    "端口映射": "port_mapping",
    "自定义服务端口协议": "custom_service_ports",
    "计费方式": "billing",
    "费用": "cost",
}

LIST_COLUMN_KEY_MAP = {
    "实例ID /名称": "identity",
    "状态": "status",
    "规格详情": "spec",
    "本地磁盘": "storage",
    "健康状态": "health",
    "付费方式": "billing",
    "释放时间/停机时间": "lifecycle",
    "SSH登录": "ssh_login",
    "快捷工具": "quick_tools",
    "操作": "actions",
}

ACTION_LABEL_KEY_MAP = {
    "查看详情": "detail",
    "开机": "start",
    "关机": "stop",
    "停止": "stop",
    "关闭": "stop",
    "设置定时关机": "schedule_shutdown",
    "更多": "more",
}

HOST_HOVER_FIELD_KEY_MAP = {
    "主机名称": "host_name",
    "可租用至": "rentable_until",
    "数据盘可扩容": "data_disk_expandable_gb",
    "GPU空闲/总量": "gpu_free_total",
    "GPU驱动": "gpu_driver",
    "CUDA版本": "cuda_version",
}

LIST_FALLBACK_HEADERS = [
    "实例ID /名称",
    "状态",
    "规格详情",
    "本地磁盘",
    "健康状态",
    "付费方式",
    "释放时间/停机时间",
    "SSH登录",
    "快捷工具",
    "操作",
]

LIST_SORT_CHOICES = (
    "site",
    "host",
    "host_name",
    "name",
    "instance_id",
    "gpu_model",
    "gpu_cards",
    "gpu_free",
    "gpu_total",
    "data_disk_expandable_gb",
    "rentable_until",
    "gpu_driver",
    "cuda_version",
    "status",
    "billing",
    "lifecycle",
)

# Require at least one digit so host aliases like "host-a" are not misread as instance ids.
INSTANCE_ID_RE = re.compile(r"\b(?=[a-z0-9-]*\d)[a-z0-9]{4,}-[a-z0-9]+\b", re.IGNORECASE)
GPU_QUOTA_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

SESSION_COOKIE_DOMAIN_SUFFIX = "autodl.com"
SESSION_COOKIE_EXPIRY_WARNING_SECONDS = 7 * 24 * 3600
