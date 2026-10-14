import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from src.core.permissions import CurrentUser
from src.api.v1.reports import get_disposition_summary_report, get_cdr_report, get_dashboard_metrics

class TestDispositionReports(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_user = CurrentUser(
            user_id=str(uuid4()),
            tenant_id=None,
            username="admin",
            email="admin@pbx.local",
            role="super_admin"
        )
        self.tenant_user = CurrentUser(
            user_id=str(uuid4()),
            tenant_id=str(uuid4()),
            username="tenant",
            email="tenant@pbx.local",
            role="tenant_admin"
        )

    @patch("src.api.v1.reports.execute_query_one")
    @patch("src.api.v1.reports.execute_query")
    async def test_get_disposition_summary_calculates_kpis(self, mock_exec_query, mock_exec_one):
        mock_exec_one.return_value = {
            "total_calls": 100,
            "answered_calls": 85,
            "no_answer_calls": 10,
            "busy_calls": 3,
            "failed_calls": 2,
            "avg_duration": 42.5,
            "avg_billsec": 38.2
        }
        mock_exec_query.return_value = [
            {"cause": "NORMAL_CLEARING", "count": 85, "avg_duration": 45.0, "avg_billsec": 42.0},
            {"cause": "NO_ANSWER", "count": 10, "avg_duration": 25.0, "avg_billsec": 0.0},
            {"cause": "USER_BUSY", "count": 3, "avg_duration": 5.0, "avg_billsec": 0.0},
            {"cause": "CALL_REJECTED", "count": 2, "avg_duration": 2.0, "avg_billsec": 0.0}
        ]

        result = await get_disposition_summary_report(
            direction="inbound",
            current_user=self.admin_user
        )

        self.assertEqual(result["total_calls"], 100)
        self.assertEqual(result["answered"], 85)
        self.assertEqual(result["no_answer"], 10)
        self.assertEqual(result["busy"], 3)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["answer_rate"], 85.0)
        self.assertEqual(len(result["breakdown"]), 4)
        self.assertEqual(result["breakdown"][0]["cause"], "NORMAL_CLEARING")
        self.assertEqual(result["breakdown"][0]["percentage"], 85.0)

    @patch("src.api.v1.reports.execute_query")
    async def test_get_cdr_report_filters_disposition_and_direction(self, mock_exec_query):
        mock_exec_query.return_value = []

        await get_cdr_report(
            direction="inbound",
            disposition="ANSWERED",
            current_user=self.tenant_user
        )

        self.assertTrue(mock_exec_query.called)
        query_sql, params = mock_exec_query.call_args[0]
        self.assertIn("c.direction = :active_dir", query_sql)
        self.assertIn("c.billsec > 0 OR c.hangup_cause = 'NORMAL_CLEARING'", query_sql)
        self.assertEqual(params["active_dir"], "inbound")
        self.assertEqual(params["t_id"], str(self.tenant_user.tenant_id))

    @patch("src.services.gateway_sync.execute_esl_command")
    @patch("src.api.v1.reports.execute_query_one")
    async def test_get_dashboard_metrics_reads_esl_live_calls(self, mock_exec_one, mock_esl):
        mock_esl.return_value = "3 total.\n"
        mock_exec_one.side_effect = [
            {"cnt": 1},  # tenants
            {"cnt": 2},  # gateways
            {"cnt": 1},  # sip_trunks
            {"cnt": 10}, # extensions
            {"cnt": 5},  # dids
            {"cnt": 3},  # queues
            {"cnt": 2},  # ivr
            {
                "in_total": 50, "in_answered": 45, "in_unanswered": 3, "in_failed": 2,
                "out_total": 20, "out_answered": 18, "out_unanswered": 1, "out_failed": 1
            },           # traffic summary
            {"inbound_peak": 12, "outbound_peak": 6} # traffic peak
        ]

        metrics = await get_dashboard_metrics(current_user=self.admin_user)
        self.assertEqual(metrics["live_calls"], 3)
        self.assertEqual(metrics["traffic_summary"]["inbound"]["total"], 50)
        self.assertEqual(metrics["traffic_summary"]["inbound"]["answered"], 45)
        self.assertEqual(metrics["traffic_peak"]["inbound_peak"], 12)
        self.assertEqual(metrics["traffic_peak"]["outbound_peak"], 6)

if __name__ == "__main__":
    unittest.main()
