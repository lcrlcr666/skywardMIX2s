#!/usr/bin/env python3
"""Send the WLAN board data (0x0025) and calibration report (0x0026) from icnss.

In this kernel branch the WLFW client lives in `drivers/soc/qcom/icnss.c` — there
is no `icnss_qmi.c` — and it speaks QMI through `msm_qmi_interface`'s
`qmi_send_req_wait()` rather than the newer `qmi_txn` API.  mainline's ath10k
sends the board file and a calibration report when the firmware reports MSA
ready, before it declares itself ready; this driver never did, which is where the
WLFW bring-up stops.

The insert is the same logic as commit bd4a0ed's `icnss_qmi.c` version, with a
log line per segment so the next boot says exactly where a send stops.

Usage: patch-icnss-bdf.py <kernel tree>
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
src = root / "drivers/soc/qcom/icnss.c"
text = src.read_text()

FUNCS = r'''
/*
 * Board data and the calibration report.
 *
 * A full QMI_WLFW_MAX_DATA_SIZE_V01 chunk does not fit the message - the TLVs
 * around it overrun the declared maximum and the encoder refuses the whole
 * message - so chunks are kept well inside it.
 */
#define BDF_CHUNK		4096

static const char *const bdf_names[] = {
	"bdwlan.bin", "bdf_d5x.bin", "bdf_e10.bin", "bdf_e5.bin", "bdwlan.b04",
	"bdwlan.b07", "bdwlan.102", "bdwlan.104",
};

static int wlfw_bdf_download_send_sync_msg(void)
{
	const struct firmware *fw = NULL;
	struct wlfw_bdf_download_req_msg_v01 req;
	struct wlfw_bdf_download_resp_msg_v01 resp;
	struct msg_desc req_desc, resp_desc;
	unsigned int remaining, sent = 0;
	const char *name = NULL;
	const u8 *data;
	int ret = 0, i;

	if (!penv || !penv->wlfw_clnt)
		return -ENODEV;

	for (i = 0; i < ARRAY_SIZE(bdf_names); i++) {
		if (!request_firmware(&fw, bdf_names[i], &penv->pdev->dev)) {
			name = bdf_names[i];
			break;
		}
	}
	if (!name) {
		icnss_pr_err("no board data file could be loaded\n");
		return -ENOENT;
	}

	icnss_pr_info("Sending board data %s (%zu bytes), state: 0x%lx\n",
		      name, fw->size, penv->state);

	req_desc.max_msg_len = WLFW_BDF_DOWNLOAD_REQ_MSG_V01_MAX_MSG_LEN;
	req_desc.msg_id = QMI_WLFW_BDF_DOWNLOAD_REQ_V01;
	req_desc.ei_array = wlfw_bdf_download_req_msg_v01_ei;

	resp_desc.max_msg_len = WLFW_BDF_DOWNLOAD_RESP_MSG_V01_MAX_MSG_LEN;
	resp_desc.msg_id = QMI_WLFW_BDF_DOWNLOAD_RESP_V01;
	resp_desc.ei_array = wlfw_bdf_download_resp_msg_v01_ei;

	data = fw->data;
	remaining = fw->size;
	icnss_pr_info("board data: %u bytes, chunks of %u\n",
		      remaining, (u32)BDF_CHUNK);

	while (remaining && !ret) {
		u32 chunk = min_t(u32, remaining, (u32)BDF_CHUNK);

		icnss_pr_info("board data: segment %u, %u bytes%s\n",
			      sent / BDF_CHUNK, chunk,
			      (chunk == remaining) ? " (last)" : "");

		memset(&req, 0, sizeof(req));
		memset(&resp, 0, sizeof(resp));

		req.valid = 1;
		req.file_id_valid = 1;
		req.file_id = 0;
		req.total_size_valid = 1;
		req.total_size = fw->size;
		req.seg_id_valid = 1;
		req.seg_id = sent / BDF_CHUNK;
		req.data_valid = 1;
		req.data_len = chunk;
		memcpy(req.data, data, chunk);
		req.end_valid = 1;
		req.end = (chunk == remaining) ? 1 : 0;

		ret = qmi_send_req_wait(penv->wlfw_clnt, &req_desc, &req,
					sizeof(req), &resp_desc, &resp,
					sizeof(resp), WLFW_TIMEOUT_MS);
		if (ret < 0) {
			icnss_pr_err("board data: segment %u got no answer %d\n",
				     req.seg_id, ret);
			break;
		}
		if (resp.resp.result != QMI_RESULT_SUCCESS_V01) {
			icnss_pr_err("board data segment %u rejected: result %d error %d\n",
				     req.seg_id, resp.resp.result,
				     resp.resp.error);
			/* the last segment's CRC is allowed to fail */
			ret = req.end ? 0 : -EINVAL;
			break;
		}

		data += req.data_len;
		remaining -= req.data_len;
		sent += req.data_len;
	}

	if (!ret)
		icnss_pr_info("board data sent: %u bytes\n", sent);

	release_firmware(fw);
	return ret;
}

static int wlfw_cal_report_send_sync_msg(void)
{
	struct wlfw_cal_report_req_msg_v01 req;
	struct wlfw_cal_report_resp_msg_v01 resp;
	struct msg_desc req_desc, resp_desc;
	int ret;

	if (!penv || !penv->wlfw_clnt)
		return -ENODEV;

	memset(&req, 0, sizeof(req));
	memset(&resp, 0, sizeof(resp));
	req.meta_data_len = 0;

	req_desc.max_msg_len = WLFW_CAL_REPORT_REQ_MSG_V01_MAX_MSG_LEN;
	req_desc.msg_id = QMI_WLFW_CAL_REPORT_REQ_V01;
	req_desc.ei_array = wlfw_cal_report_req_msg_v01_ei;

	resp_desc.max_msg_len = WLFW_CAL_REPORT_RESP_MSG_V01_MAX_MSG_LEN;
	resp_desc.msg_id = QMI_WLFW_CAL_REPORT_RESP_V01;
	resp_desc.ei_array = wlfw_cal_report_resp_msg_v01_ei;

	ret = qmi_send_req_wait(penv->wlfw_clnt, &req_desc, &req, sizeof(req),
				&resp_desc, &resp, sizeof(resp),
				WLFW_TIMEOUT_MS);
	if (ret < 0) {
		icnss_pr_err("cal report: no answer %d\n", ret);
		return ret;
	}
	if (resp.resp.result != QMI_RESULT_SUCCESS_V01) {
		icnss_pr_err("cal report rejected: result %d error %d\n",
			     resp.resp.result, resp.resp.error);
		return -EINVAL;
	}

	icnss_pr_info("cal report sent\n");
	return 0;
}

'''

changed = []


def need(cond, what):
    if not cond:
        raise SystemExit(f"drivers/soc/qcom/icnss.c: {what}")


# 1. request_firmware()/release_firmware()
if "#include <linux/firmware.h>" not in text:
    anchor = "#include <soc/qcom/msm_qmi_interface.h>"
    need(anchor in text, "expected the msm_qmi_interface include")
    text = text.replace(anchor, "#include <linux/firmware.h>\n" + anchor, 1)
    changed.append("include")

# 2. the two sending routines, just before the capability request
if "wlfw_bdf_download_send_sync_msg" not in text:
    anchor = "static int wlfw_cap_send_sync_msg(void)"
    need(text.count(anchor) == 1, "expected one wlfw_cap_send_sync_msg definition")
    text = text.replace(anchor, FUNCS.lstrip("\n") + anchor, 1)
    changed.append("board data + calibration report")

# 3. call them once the firmware has taken the capability message
if "wlfw_bdf_download_send_sync_msg()" not in text.replace(anchor, ""):
    call_anchor = """	ret = wlfw_cap_send_sync_msg();
	if (ret < 0)
		goto err_setup_msa;
"""
    need(call_anchor in text, "expected the capability request in the arrive sequence")
    text = text.replace(call_anchor, call_anchor + """
	/* mainline's ath10k hands the firmware its board data and a calibration
	 * report from the MSA-ready indication, and this firmware withholds its
	 * ready indication until it has them.  Best effort, and logged, so the
	 * boot says where the send stops. */
	if (!wlfw_bdf_download_send_sync_msg())
		wlfw_cal_report_send_sync_msg();
""", 1)
    changed.append("call in the arrive sequence")

src.write_text(text)
print("icnss board data:", ", ".join(changed) if changed else "nothing to do")
