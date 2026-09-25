"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { BuilderIdStatus } from "../lib/types";
import { builderIdLabel, builderIdNotice, safeErrorMessage, type BuilderIdNotice } from "../lib/view";
import { Icon } from "./Icon";

export function BuilderIdControl() {
  const [status, setStatus] = useState<BuilderIdStatus>({ state: "not_connected" });
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState<BuilderIdNotice | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (notice && !dialog.open) dialog.showModal();
    if (!notice && dialog.open) dialog.close();
  }, [notice]);

  useEffect(() => {
    let active = true;
    api.builderIdStatus().then((value) => {
      if (active) { setStatus(value); setNotice(builderIdNotice(value.state, value.failure_reason)); }
    }).catch(() => {
      if (active) setNotice({ title: "Sign-in unavailable", message: safeErrorMessage("auth"), tone: "danger" });
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (status.state !== "connecting") return;
    const timer = window.setInterval(() => {
      api.builderIdStatus().then((value) => {
        setStatus(value);
        if (value.state !== "connecting") setAuthorizationUrl(null);
        if (value.state !== "connecting") setNotice(builderIdNotice(value.state, value.failure_reason));
      }).catch(() => setNotice((current) => current ?? { title: "Sign-in unavailable", message: safeErrorMessage("auth"), tone: "danger" }));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [status.state]);

  async function signIn() {
    setNotice(null);
    const signInTab = window.open("about:blank", "_blank");
    if (signInTab) signInTab.opener = null;
    try {
      const result = await api.startBuilderIdLogin();
      setStatus({ state: result.state, failure_reason: result.failure_reason });
      setAuthorizationUrl(result.authorization_url ?? null);
      if (result.authorization_url) {
        if (signInTab) signInTab.location.href = result.authorization_url;
        else setNotice({ title: "Sign-in page blocked", message: "Your browser blocked the AWS sign-in tab. Select Open sign-in page in the top bar to continue.", tone: "warning" });
      } else {
        signInTab?.close();
        setNotice(builderIdNotice(result.state, result.failure_reason));
      }
    } catch (reason) {
      signInTab?.close();
      setStatus({ state: "not_connected" });
      setNotice({ title: "Sign-in unavailable", message: safeErrorMessage(reason instanceof ApiError ? reason.kind : "auth"), tone: "danger" });
    }
  }

  const state = status.state;
  return <div className="auth-control">
    {state === "not_connected" || state === "sign_in_failed" ?
      <button type="button" className="auth-control-button" onClick={signIn}><Icon name="shield" size={13} />{builderIdLabel(state)}</button> :
      <span role="status" className={`auth-control-status ${state === "registration_required" || state === "access_unavailable" ? "warning" : state === "live_aws" ? "connected" : ""}`}><span aria-hidden="true" className="auth-indicator" />{builderIdLabel(state)}</span>}
    {state === "connecting" && (authorizationUrl ?
      <a className="auth-control-reopen" href={authorizationUrl} target="_blank" rel="noopener noreferrer">Open sign-in page</a> :
      <button type="button" className="auth-control-reopen" onClick={signIn}>Open sign-in page</button>)}
    <dialog ref={dialogRef} className="auth-dialog" aria-labelledby="auth-dialog-title" aria-describedby="auth-dialog-message" onClose={() => setNotice(null)}>
      {notice && <div className="auth-dialog-content">
        <div className={`auth-dialog-mark ${notice.tone}`} aria-hidden="true"><Icon name="shield" size={20} /></div>
        <div className="eyebrow">AWS BUILDER ID</div>
        <h2 id="auth-dialog-title" className="auth-dialog-title">{notice.title}</h2>
        <p id="auth-dialog-message" className="auth-dialog-message">{notice.message}</p>
        <div className="auth-dialog-actions">
          <button type="button" className="button-secondary" onClick={() => setNotice(null)}>Continue with demo</button>
          {state === "sign_in_failed" || state === "not_connected" ? <button type="button" className="button-primary" onClick={signIn}>Try sign-in again</button> : null}
        </div>
      </div>}
    </dialog>
  </div>;
}
