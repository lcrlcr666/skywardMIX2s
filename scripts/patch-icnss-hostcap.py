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


for path, edit in ((qmi, add_function), (hdrs, add_prototype), (core, call_it)):
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

