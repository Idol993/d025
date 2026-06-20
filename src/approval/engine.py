"""
分级审批流转引擎
- 常规迭代串行审批
- 紧急热修复并行审批
- 动态审批矩阵
- 超时升级与事后补签
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

from ..common.utils import format_datetime, save_json, ensure_dir, generate_release_id


class ApprovalStatus(str, Enum):
    """审批状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    POST_SIGNED = "post_signed"


class ReleaseChannel(str, Enum):
    """发布通道"""
    NORMAL = "normal"
    HOTFIX = "hotfix"


class ApprovalNode:
    """审批节点"""

    def __init__(self, node_id: str, role: str, department: str, order: int = 0):
        self.node_id = node_id
        self.role = role
        self.department = department
        self.order = order
        self.status = ApprovalStatus.PENDING
        self.approver = None
        self.approval_time = None
        self.comment = ""
        self.attachment = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "department": self.department,
            "order": self.order,
            "status": self.status.value,
            "approver": self.approver,
            "approval_time": self.approval_time,
            "comment": self.comment,
            "attachment": self.attachment
        }


class ApprovalFlow:
    """审批流"""

    def __init__(self, flow_id: str, channel: ReleaseChannel, release_id: str):
        self.flow_id = flow_id
        self.channel = channel
        self.release_id = release_id
        self.nodes: Dict[str, ApprovalNode] = {}
        self.create_time = format_datetime()
        self.update_time = format_datetime()
        self.current_node_id = None
        self.overall_status = ApprovalStatus.PENDING
        self.emergency_reason = ""
        self.deviation_report = None

    def add_node(self, node: ApprovalNode):
        self.nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[ApprovalNode]:
        return self.nodes.get(node_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "channel": self.channel.value,
            "release_id": self.release_id,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "create_time": self.create_time,
            "update_time": self.update_time,
            "current_node_id": self.current_node_id,
            "overall_status": self.overall_status.value,
            "emergency_reason": self.emergency_reason,
            "deviation_report": self.deviation_report
        }


class ApprovalEngine:
    """审批引擎"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.approval_config = config.get("approval", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")
        self.approvers_config = self.approval_config.get("approvers", {})
        self.serial_flow = self.approval_config.get("serial_flow", [])
        self.parallel_flow = self.approval_config.get("parallel_flow", [])
        self.channels_config = self.approval_config.get("channels", {})

    def create_approval_flow(self, release_id: str, channel: str,
                             emergency_reason: str = "") -> ApprovalFlow:
        """创建审批流"""
        flow_id = generate_release_id("APV")
        release_channel = ReleaseChannel(channel)
        flow = ApprovalFlow(flow_id, release_channel, release_id)

        if release_channel == ReleaseChannel.HOTFIX:
            flow.emergency_reason = emergency_reason

        node_order = 0
        node_list = self.serial_flow if release_channel == ReleaseChannel.NORMAL else self.parallel_flow

        for node_id in node_list:
            approver_info = self.approvers_config.get(node_id, {})
            node = ApprovalNode(
                node_id=node_id,
                role=approver_info.get("role", node_id),
                department=approver_info.get("department", ""),
                order=node_order
            )
            flow.add_node(node)
            node_order += 1

        if release_channel == ReleaseChannel.NORMAL and self.serial_flow:
            flow.current_node_id = self.serial_flow[0]

        self._save_flow(flow)
        self.logger.info(f"创建审批流 {flow_id} - 发布: {release_id}, 通道: {channel}")
        return flow

    def approve(self, flow_id: str, node_id: str, approver: str,
                comment: str = "", attachment: Any = None) -> Dict[str, Any]:
        """审批通过"""
        flow = self._load_flow(flow_id)
        if not flow:
            return {"success": False, "message": "审批流不存在"}

        node = flow.get_node(node_id)
        if not node:
            return {"success": False, "message": "审批节点不存在"}

        if node.status != ApprovalStatus.PENDING:
            return {"success": False, "message": f"该节点当前状态为{node.status.value}，无法审批"}

        node.status = ApprovalStatus.APPROVED
        node.approver = approver
        node.approval_time = format_datetime()
        node.comment = comment
        node.attachment = attachment

        flow.update_time = format_datetime()

        if flow.channel == ReleaseChannel.NORMAL:
            self._advance_serial_flow(flow, node_id)
        else:
            self._check_parallel_flow_complete(flow)

        self._save_flow(flow)
        self.logger.info(f"审批通过 - 流程: {flow_id}, 节点: {node_id}, 审批人: {approver}")

        return {
            "success": True,
            "message": "审批通过",
            "flow_status": flow.overall_status.value,
            "current_node": flow.current_node_id,
            "flow": flow.to_dict()
        }

    def reject(self, flow_id: str, node_id: str, approver: str,
               reject_reason: str = "", attachment: Any = None) -> Dict[str, Any]:
        """驳回审批"""
        flow = self._load_flow(flow_id)
        if not flow:
            return {"success": False, "message": "审批流不存在"}

        node = flow.get_node(node_id)
        if not node:
            return {"success": False, "message": "审批节点不存在"}

        if node.status != ApprovalStatus.PENDING:
            return {"success": False, "message": f"该节点当前状态为{node.status.value}，无法驳回"}

        node.status = ApprovalStatus.REJECTED
        node.approver = approver
        node.approval_time = format_datetime()
        node.comment = reject_reason
        node.attachment = attachment

        flow.overall_status = ApprovalStatus.REJECTED
        flow.update_time = format_datetime()

        for n in flow.nodes.values():
            if n.status == ApprovalStatus.PENDING:
                n.status = ApprovalStatus.SKIPPED

        self._save_flow(flow)
        self.logger.info(f"审批驳回 - 流程: {flow_id}, 节点: {node_id}, 审批人: {approver}, 原因: {reject_reason}")

        return {
            "success": True,
            "message": "审批已驳回",
            "flow_status": flow.overall_status.value,
            "flow": flow.to_dict()
        }

    def _advance_serial_flow(self, flow: ApprovalFlow, current_node_id: str):
        """推进串行审批流"""
        current_index = None
        for i, node_id in enumerate(self.serial_flow):
            if node_id == current_node_id:
                current_index = i
                break

        if current_index is None:
            return

        if current_index + 1 < len(self.serial_flow):
            next_node_id = self.serial_flow[current_index + 1]
            flow.current_node_id = next_node_id
        else:
            flow.overall_status = ApprovalStatus.APPROVED
            flow.current_node_id = None

    def _check_parallel_flow_complete(self, flow: ApprovalFlow):
        """检查并行审批流是否完成"""
        approved_count = sum(1 for n in flow.nodes.values() if n.status == ApprovalStatus.APPROVED)
        total_count = len(flow.nodes)
        pending_count = sum(1 for n in flow.nodes.values() if n.status == ApprovalStatus.PENDING)

        if approved_count >= 1:
            flow.overall_status = ApprovalStatus.APPROVED
            flow.current_node_id = None
            return

        if pending_count == 0 and approved_count == 0:
            flow.overall_status = ApprovalStatus.REJECTED

    def post_signoff(self, flow_id: str, node_id: str, approver: str,
                     comment: str = "") -> Dict[str, Any]:
        """事后补签（紧急发布用）"""
        flow = self._load_flow(flow_id)
        if not flow:
            return {"success": False, "message": "审批流不存在"}

        if flow.channel != ReleaseChannel.HOTFIX:
            return {"success": False, "message": "仅紧急发布支持事后补签"}

        node = flow.get_node(node_id)
        if not node:
            return {"success": False, "message": "审批节点不存在"}

        if node.status == ApprovalStatus.APPROVED:
            return {"success": False, "message": "该节点已审批，无需补签"}

        node.status = ApprovalStatus.POST_SIGNED
        node.approver = approver
        node.approval_time = format_datetime()
        node.comment = comment

        flow.update_time = format_datetime()

        all_signed = all(n.status in [ApprovalStatus.APPROVED, ApprovalStatus.POST_SIGNED]
                         for n in flow.nodes.values())

        self._save_flow(flow)
        self.logger.info(f"事后补签 - 流程: {flow_id}, 节点: {node_id}, 审批人: {approver}")

        return {
            "success": True,
            "message": "补签成功",
            "all_signed": all_signed,
            "flow": flow.to_dict()
        }

    def get_approval_status(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """获取审批状态"""
        flow = self._load_flow(flow_id)
        if not flow:
            return None
        return flow.to_dict()

    def get_pending_approvals(self, role: str = None) -> List[Dict[str, Any]]:
        """获取待审批列表"""
        pending_list = []
        flow_dir = f"{self.data_path}/approvals"
        ensure_dir(flow_dir)

        import os
        for filename in os.listdir(flow_dir):
            if not filename.endswith(".json"):
                continue
            flow_data = self._load_flow_by_path(os.path.join(flow_dir, filename))
            if not flow_data:
                continue

            if flow_data.overall_status != ApprovalStatus.PENDING:
                continue

            if role and role not in flow_data.nodes:
                continue

            if role:
                node = flow_data.nodes.get(role)
                if node and node.status == ApprovalStatus.PENDING:
                    pending_list.append(flow_data.to_dict())
            else:
                pending_list.append(flow_data.to_dict())

        return pending_list

    def get_approval_summary(self, flow_id: str) -> str:
        """生成审批摘要"""
        flow = self._load_flow(flow_id)
        if not flow:
            return "审批流不存在"

        lines = []
        channel_name = self.channels_config.get(flow.channel.value, {}).get("name", flow.channel.value)

        lines.append("=" * 50)
        lines.append("审批流程摘要")
        lines.append("=" * 50)
        lines.append(f"流程ID: {flow.flow_id}")
        lines.append(f"发布ID: {flow.release_id}")
        lines.append(f"发布通道: {channel_name}")
        lines.append(f"创建时间: {flow.create_time}")
        lines.append(f"状态: {flow.overall_status.value}")
        lines.append("")

        if flow.emergency_reason:
            lines.append(f"紧急原因: {flow.emergency_reason}")
            lines.append("")

        lines.append("审批节点:")
        lines.append("-" * 30)

        sorted_nodes = sorted(flow.nodes.values(), key=lambda n: n.order)
        for node in sorted_nodes:
            prefix = "  "
            if flow.current_node_id == node.node_id:
                prefix = "▶ "

            status_text = {
                "pending": "待审批",
                "approved": "已通过",
                "rejected": "已驳回",
                "skipped": "已跳过",
                "timeout": "已超时",
                "post_signed": "事后补签"
            }.get(node.status.value, node.status.value)

            lines.append(f"{prefix}[{status_text}] {node.role} ({node.department})")

            if node.approver:
                lines.append(f"    审批人: {node.approver}")
            if node.approval_time:
                lines.append(f"    审批时间: {node.approval_time}")
            if node.comment:
                lines.append(f"    审批意见: {node.comment}")
            lines.append("")

        lines.append("=" * 50)

        return "\n".join(lines)

    def _save_flow(self, flow: ApprovalFlow):
        """保存审批流"""
        try:
            flow_dir = f"{self.data_path}/approvals"
            ensure_dir(flow_dir)
            file_path = f"{flow_dir}/{flow.flow_id}.json"
            save_json(flow.to_dict(), file_path)
        except Exception as e:
            self.logger.error(f"保存审批流失败: {e}")

    def _load_flow(self, flow_id: str) -> Optional[ApprovalFlow]:
        """加载审批流"""
        file_path = f"{self.data_path}/approvals/{flow_id}.json"
        return self._load_flow_by_path(file_path)

    def _load_flow_by_path(self, file_path: str) -> Optional[ApprovalFlow]:
        """从文件路径加载审批流"""
        import os
        if not os.path.exists(file_path):
            return None

        try:
            from ..common.utils import load_json
            data = load_json(file_path)
            if not data:
                return None

            flow = ApprovalFlow(data["flow_id"], ReleaseChannel(data["channel"]), data["release_id"])
            flow.create_time = data.get("create_time", flow.create_time)
            flow.update_time = data.get("update_time", flow.update_time)
            flow.current_node_id = data.get("current_node_id")
            flow.overall_status = ApprovalStatus(data.get("overall_status", "pending"))
            flow.emergency_reason = data.get("emergency_reason", "")
            flow.deviation_report = data.get("deviation_report")

            for node_id, node_data in data.get("nodes", {}).items():
                node = ApprovalNode(
                    node_id=node_data["node_id"],
                    role=node_data.get("role", ""),
                    department=node_data.get("department", ""),
                    order=node_data.get("order", 0)
                )
                node.status = ApprovalStatus(node_data.get("status", "pending"))
                node.approver = node_data.get("approver")
                node.approval_time = node_data.get("approval_time")
                node.comment = node_data.get("comment", "")
                node.attachment = node_data.get("attachment")
                flow.add_node(node)

            return flow
        except Exception as e:
            self.logger.error(f"加载审批流失败: {e}")
            return None
