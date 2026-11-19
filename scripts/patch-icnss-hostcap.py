#!/usr/bin/env python3
"""Make icnss send the WLFW host-capability message before it waits for ready.

The chain this recovery is stuck on:

    icnss_wlan_enable()  refuses until ICNSS_FW_READY
    ICNSS_FW_READY       is set only by QMI_WLFW_FW_READY_IND_V01 (0x0021)
    that indication      never arrives
    QMI_WLFW_HOST_CAP_REQ_V01 (0x0034), the host's capabilities, is declared
                         in the WLFW IDL that ships with this tree - and never
                         sent: grep host_cap finds nothing in icnss.c or
                         icnss_qmi.c

The installed system runs a newer kernel tree, which is where such a message
would have been added.  So it is added here: a send-sync message built with the
IDL's own encoder, sent right after the capability request and before the
dynamic feature mask, which is where a newer icnss would put it.

Usage: patch-icnss-hostcap.py <kernel tree>
"""

import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
qmi = root / "drivers/soc/qcom/icnss_qmi.c"
hdrs = root / "drivers/soc/qcom/icnss_qmi.h"
core = root / "drivers/soc/qcom/icnss.c"
changed = []

FUNC = r'''
/**
 * wlfw_host_cap_send_sync_msg() - tell the firmware what this host can do
 * @priv: icnss private handle
 *
 * The firmware withholds its ready indication until it has been told the
 * host's capabilities; the tree's WLFW IDL declares the message and this
 * driver never sent it.
 */
int wlfw_host_cap_send_sync_msg(struct icnss_priv *priv)
{
	struct wlfw_host_cap_req_msg_v01 *req;
	struct wlfw_host_cap_resp_msg_v01 *resp;
	struct qmi_txn txn;
	int ret;

	if (!priv)
		return -ENODEV;

	icnss_pr_dbg("Sending host capability message, state: 0x%lx\n",
		     priv->state);

	req = kzalloc(sizeof(*req), GFP_KERNEL);
	if (!req)
		return -ENOMEM;
	resp = kzalloc(sizeof(*resp), GFP_KERNEL);
	if (!resp) {
		kfree(req);
		return -ENOMEM;
	}

	req->num_clients_valid = 1;
	req->num_clients = 1;
	req->wake_msi_valid = 1;
	req->wake_msi = 0;
	req->gpios_valid = 1;
	req->gpios_len = 0;

	ret = qmi_txn_init(&priv->qmi, &txn,
			   wlfw_host_cap_resp_msg_v01_ei, resp);
	if (ret < 0) {
		icnss_qmi_fatal_err("Fail to init txn for Host Cap resp %d\n",
				    ret);
		goto out;
	}

	ret = qmi_send_request(&priv->qmi, NULL, &txn,
			       QMI_WLFW_HOST_CAP_REQ_V01,
			       WLFW_HOST_CAP_REQ_MSG_V01_MAX_MSG_LEN,
			       wlfw_host_cap_req_msg_v01_ei, req);
	if (ret < 0) {
		qmi_txn_cancel(&txn);
		icnss_qmi_fatal_err("Fail to send Host Cap req %d\n", ret);
		goto out;
	}

	ret = qmi_txn_wait(&txn, WLFW_TIMEOUT);
	if (ret < 0) {
		icnss_qmi_fatal_err("Host Cap resp wait failed with ret %d\n",
				    ret);
		goto out;
	} else if (resp->resp.result != QMI_RESULT_SUCCESS_V01) {
		icnss_qmi_fatal_err("QMI Host Cap request rejected, result:%d error:%d\n",
				    resp->resp.result, resp->resp.error);
		ret = -resp->resp.result;
		goto out;
	}

out:
	kfree(req);
	kfree(resp);
	return ret;
}

'''


def add_function(text):
    anchor = "int wlfw_cap_send_sync_msg(struct icnss_priv *priv"
    if "wlfw_host_cap_send_sync_msg(struct icnss_priv *priv)" in text:
        return text
    if anchor not in text:
        return text
    return text.replace(anchor, FUNC.lstrip("\n") + anchor, 1)


def add_prototype(text):
    if "wlfw_host_cap_send_sync_msg" in text:
        return text
    anchor = "int wlfw_cap_send_sync_msg(struct icnss_priv *priv);"
    if anchor not in text:
        return text
    return text.replace(anchor, anchor + "\nint wlfw_host_cap_send_sync_msg(struct icnss_priv *priv);", 1)


def call_it(text):
    if "wlfw_host_cap_send_sync_msg" in text:
        return text
    # Mainline's ath10k sends the host capabilities first, before the memory
    # handshake, and treats a rejection as harmless ("older FW didn't support
    # this request, which is not fatal").  This firmware rejects it when it
    # comes late, which is where the first attempt put it.
    anchor = """		ignore_assert = true;
		goto fail;
	}

	if (!penv->msa_va) {"""
    if anchor not in text:
        return text
    replacement = """		ignore_assert = true;
		goto fail;
	}

	/* Not fatal: firmware older than this message simply says so. */
	wlfw_host_cap_send_sync_msg(penv);

	if (!penv->msa_va) {"""
    return text.replace(anchor, replacement, 1)


def sleep_before_xpu(text):
    if "MPSS.AT.4.0" in text:
        return text
    anchor = """	if (!test_bit(ICNSS_MSA0_ASSIGNED, &penv->state)) {"""
    if anchor not in text:
        return text
    # Mainline's ath10k does exactly this on SDM845, with the reason in the
    # comment it carries: "sleep for a while inbetween receiving the msa info
    # response and the XPU update to prevent SDM845 from crashing due to a
    # security violation, when running MPSS.AT.4.0.c2-01184-SDM845_GEN_PACK-1".
    # This phone runs MPSS.AT.4.0.c2.6-00335-SDM845_GEN_PACK-1.
    replacement = """	msleep(20);	/* MPSS.AT.4.0 needs the gap before the XPU update */

""" + anchor
    return text.replace(anchor, replacement, 1)


def force_probe(text):
    """Probe the driver even though the firmware never said it is ready.

    icnss calls icnss_call_driver_probe() only from the FW_READY event, and the
    driver sends QMI_WLFW_WLAN_MODE_REQ from its probe.  If this firmware waits
    for that request before it declares itself ready, the two wait for each
    other.  Breaking it from the host side is the experiment: mark the firmware
    ready when it is merely connected, so the probe happens and the mode
    request goes out.
    """
    if "forced: the firmware" in text:
        return text
    anchor = """	if (!test_bit(ICNSS_FW_READY, &penv->state)) {
		icnss_pr_dbg("FW is not ready yet, state: 0x%lx\\n",
			     penv->state);
		goto out;
	}"""
    if anchor not in text:
        return text
    replacement = """	if (!test_bit(ICNSS_FW_READY, &penv->state)) {
		/* forced: the firmware is connected, so let the driver come up
		 * and send its mode request; the ready indication may follow. */
		icnss_pr_err("FW is not ready, probing anyway, state: 0x%lx\\n",
			     penv->state);
		set_bit(ICNSS_FW_READY, &penv->state);
	}"""
    return text.replace(anchor, replacement, 1)


BDF_AND_CAL = r"""
/**
 * wlfw_bdf_download_send_sync() - hand the firmware its board data
 * @priv: icnss private handle
 *
 * mainline's ath10k sends the board file from the MSA-ready indication, before
 * the firmware declares itself ready - and this firmware never declares itself
 * ready while nothing is ever downloaded.  The phone keeps its board files on
 * the modem partition (bdwlan.*, bdf_*.bin); the first one that loads is sent,
 * and the name that worked is printed, since that is the part the vendor tree
 * decides from a board id this firmware reports as 0xff.
 */
static const char *const bdf_names[] = {
	"bdwlan.bin", "bdf_d5x.bin", "bdf_e10.bin", "bdf_e5.bin", "bdwlan.b04",
	"bdwlan.b07", "bdwlan.102", "bdwlan.104",
};

int wlfw_bdf_download_send_sync(struct icnss_priv *priv)
{
	struct wlfw_bdf_download_req_msg_v01 *req;
	struct wlfw_bdf_download_resp_msg_v01 *resp;
	const struct firmware *fw = NULL;
	const u8 *data;
	unsigned int remaining, sent = 0;
	struct qmi_txn txn;
	const char *name = NULL;
	int ret = 0, i;

	if (!priv)
		return -ENODEV;

	for (i = 0; i < ARRAY_SIZE(bdf_names); i++) {
		if (!request_firmware(&fw, bdf_names[i], &priv->pdev->dev)) {
			name = bdf_names[i];
			break;
		}
	}
	if (!name) {
		icnss_pr_err("no board data file could be loaded\n");
		return -ENOENT;
	}

	icnss_pr_info("Sending board data %s (%zu bytes), state: 0x%lx\n",
		      name, fw->size, priv->state);

	req = kzalloc(sizeof(*req), GFP_KERNEL);
	if (!req) {
		release_firmware(fw);
		return -ENOMEM;
	}
	resp = kzalloc(sizeof(*resp), GFP_KERNEL);
	if (!resp) {
		kfree(req);
		release_firmware(fw);
		return -ENOMEM;
	}

	data = fw->data;
	remaining = fw->size;
	while (remaining && !ret) {
		req->valid = 1;
		req->file_id_valid = 1;
		req->file_id = 0;
		req->total_size_valid = 1;
		req->total_size = fw->size;
		req->seg_id_valid = 1;
		req->seg_id = sent / QMI_WLFW_MAX_DATA_SIZE_V01;
		req->data_valid = 1;
		req->end_valid = 1;
		req->end = 0;
		req->data_len = min_t(u32, remaining,
				      (u32)QMI_WLFW_MAX_DATA_SIZE_V01);
		if (req->data_len == remaining)
			req->end = 1;
		memcpy(req->data, data, req->data_len);

		ret = qmi_txn_init(&priv->qmi, &txn,
				   wlfw_bdf_download_resp_msg_v01_ei, resp);
		if (ret < 0) {
			icnss_pr_err("board data: txn init failed %d\n", ret);
			break;
		}
		ret = qmi_send_request(&priv->qmi, NULL, &txn,
				       QMI_WLFW_BDF_DOWNLOAD_REQ_V01,
				       WLFW_BDF_DOWNLOAD_REQ_MSG_V01_MAX_MSG_LEN,
				       wlfw_bdf_download_req_msg_v01_ei, req);
		if (ret < 0) {
			qmi_txn_cancel(&txn);
			icnss_pr_err("board data: send of segment %u failed %d\n",
				     req->seg_id, ret);
			break;
		}
		ret = qmi_txn_wait(&txn, WLFW_TIMEOUT);
		if (ret < 0) {
			icnss_pr_err("board data: segment %u got no answer %d\n",
				     req->seg_id, ret);
			break;
		}
		if (resp->resp.result != QMI_RESULT_SUCCESS_V01) {
			/* the last segment's CRC is allowed to fail */
			icnss_pr_err("board data segment %u rejected: result %d error %d\n",
				     req->seg_id, resp->resp.result,
				     resp->resp.error);
			if (!req->end)
				ret = -EINVAL;
			else
				ret = 0;
			break;
		}
		data += req->data_len;
		remaining -= req->data_len;
		sent += req->data_len;
	}

	if (!ret)
		icnss_pr_info("board data sent: %u bytes\n", sent);

	kfree(req);
	kfree(resp);
	release_firmware(fw);
	return ret;
}

/** wlfw_cal_report_send_sync() - report that the host has no calibration to give */
int wlfw_cal_report_send_sync(struct icnss_priv *priv)
{
	struct wlfw_cal_report_req_msg_v01 *req;
	struct wlfw_cal_report_resp_msg_v01 *resp;
	struct qmi_txn txn;
	int ret;

	if (!priv)
		return -ENODEV;

	req = kzalloc(sizeof(*req), GFP_KERNEL);
	if (!req)
		return -ENOMEM;
	resp = kzalloc(sizeof(*resp), GFP_KERNEL);
	if (!resp) {
		kfree(req);
		return -ENOMEM;
	}

	ret = qmi_txn_init(&priv->qmi, &txn,
			   wlfw_cal_report_resp_msg_v01_ei, resp);
	if (ret < 0)
		goto out;
	ret = qmi_send_request(&priv->qmi, NULL, &txn,
			       QMI_WLFW_CAL_REPORT_REQ_V01,
			       WLFW_CAL_REPORT_REQ_MSG_V01_MAX_MSG_LEN,
			       wlfw_cal_report_req_msg_v01_ei, req);
	if (ret < 0) {
		qmi_txn_cancel(&txn);
		goto out;
	}
	ret = qmi_txn_wait(&txn, WLFW_TIMEOUT);
	if (ret < 0)
		goto out;
	if (resp->resp.result != QMI_RESULT_SUCCESS_V01) {
		icnss_pr_err("cal report rejected: result %d error %d\n",
			     resp->resp.result, resp->resp.error);
		ret = -EINVAL;
	}
out:
	kfree(req);
	kfree(resp);
	return ret;
}
"""


def add_bdf_and_cal(text):
    if "wlfw_bdf_download_send_sync" in text:
        return text
    anchor = "int wlfw_cap_send_sync_msg(struct icnss_priv *priv"
    if anchor not in text:
        return text
    return text.replace(anchor, BDF_AND_CAL.lstrip("\n") + anchor, 1)


def add_firmware_include(text):
    if "linux/firmware.h" in text:
        return text
    anchor = "#include <linux/slab.h>"
    if anchor not in text:
        return text
    return text.replace(anchor, anchor + "\n#include <linux/firmware.h>", 1)


def add_bdf_prototypes(text):
    if "wlfw_bdf_download_send_sync" in text:
        return text
    anchor = "int wlfw_host_cap_send_sync_msg(struct icnss_priv *priv);"
    if anchor not in text:
        return text
    return text.replace(anchor, anchor +
        "\nint wlfw_bdf_download_send_sync(struct icnss_priv *priv);"
        "\nint wlfw_cal_report_send_sync(struct icnss_priv *priv);", 1)


def call_bdf_and_cal(text):
    if "wlfw_bdf_download_send_sync(penv)" in text:
        return text
    anchor = """	ret = wlfw_cap_send_sync_msg(penv);
	if (ret < 0) {
		ignore_assert = true;
		goto err_setup_msa;
	}"""
    if anchor not in text:
        return text
    replacement = anchor + """

	/* mainline's ath10k hands over the board data and its calibration
	 * report from the MSA-ready indication; this firmware waits for them
	 * before it declares itself ready.  Best effort: the flow continues
	 * either way and the log says what happened. */
	if (!wlfw_bdf_download_send_sync(penv))
		wlfw_cal_report_send_sync(penv);"""
    return text.replace(anchor, replacement, 1)


for path, edit in ((qmi, add_function), (qmi, add_bdf_and_cal), (qmi, add_firmware_include), (hdrs, add_prototype), (hdrs, add_bdf_prototypes), (core, call_it), (core, sleep_before_xpu), (core, force_probe), (core, call_bdf_and_cal)):
    if not path.exists():
        print(f"missing: {path}")
        continue
    text = path.read_text(errors="replace")
    new = edit(text)
    if new != text:
        path.write_text(new)
        changed.append(path.name)
        print(f"patched: {path.name}")
    else:
        print(f"unchanged: {path.name}")

print("changed:", ", ".join(changed) if changed else "nothing")






