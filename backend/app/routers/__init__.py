"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import resource, cross_module, sharing

# sharing 含 /api/sharing/summaries 这类两段固定路径，必须排在资源路由
# /api/{module}/{entry_id} 之前注册，否则会被动态路径抢先匹配。
ROUTERS = [sharing, cross_module, resource]