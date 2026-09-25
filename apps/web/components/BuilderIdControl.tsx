"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { BuilderIdStatus, PathfinderMode } from "../lib/types";
import { builderIdLabel, builderIdNotice, safeErrorMessage, type BuilderIdNotice } from "../lib/view";
import { Icon } from "./Icon";

export function BuilderIdControl({ onStatusChange, loginRequest, mode, showControl, onContinueDemo }: {
  onStatusChange?: (status: BuilderIdStatus) => void;
  loginRequest?: number;
  mode: PathfinderMode;
  showControl: boolean;
  onContinueDemo?: () => void;
}) {
  const [status, setStatus] = useState<BuilderIdStatus>({ state: "not_connected" });
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState<BuilderIdNotice | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const lastRequest = useRef(0);
  const showControlRef = useRef(showControl);
  showControlRef.current = showControl;

  function updateStatus(value: BuilderIdStatus) {
    setStatus(value);
    onStatusChange?.(value);
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (notice && !dialog.open) dialog.showModal();
    if (!notice && dialog.open) dialog.close();
  }, [notice]);

  useEffect(() => {
    let active = true;
    api.builderIdStatus().then((value) => {
      if (active) { updateStatus(value); if (showControlRef.current) setNotice(builderIdNotice(value.state, value.failure_reason)); }
    }).catch(() => {
      if (active && showControlRef.current) setNotice({ title: "Sign-in unavailable", message: safeErrorMessage("auth"), tone: "danger" });
    });
    return () => { active = false; };
  }, []); // Initial connection check happens once per mounted control.

  useEffect(() => {
    if (!loginRequest || loginRequest === lastRequest.current) return;
    lastRequest.current = loginRequest;
    if (status.state === "access_unavailable" && status.failure_reason === "authentication_failed") {
      void signIn();
    } else if (status.state === "registration_required" || status.state === "access_unavailable") {
      setNotice(null);
      updateStatus({ state: "connecting" });
      api.recheckBuilderIdAccess().then((value) => {
        updateStatus(value);
        if (showControlRef.current) setNotice(builderIdNotice(value.state, value.failure_reason));
      }).catch(() => {
        updateStatus({ state: "access_unavailable", failure_reason: "transport_failure" });
        if (showControlRef.current) setNotice(builderIdNotice("access_unavailable", "transport_failure"));
      });
    } else if (status.state !== "live_aws" && status.state !== "connecting") {
      void signIn();
    }
  }, [loginRequest]);

  useEffect(() => {
    if (status.state !== "connecting") return;
    const timer = window.setInterval(() => {
      api.builderIdStatus().then((value) => {
        updateStatus(value);
        if (value.state !== "connecting") setAuthorizationUrl(null);
        if (value.state !== "connecting" && showControlRef.current) setNotice(builderIdNotice(value.state, value.failure_reason));
      }).catch(() => { if (showControlRef.current) setNotice((current) => current ?? { title: "Sign-in unavailable", message: safeErrorMessage("auth"), tone: "danger" }); });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [status.state]);

  async function signIn() {
    setNotice(null);
    const signInTab = window.open("about:blank", "_blank");
    if (signInTab) signInTab.opener = null;
    try {
      const result = await api.startBuilderIdLogin();
      updateStatus({ state: result.state, failure_reason: result.failure_reason });
      setAuthorizationUrl(result.authorization_url ?? null);
      if (result.authorization_url) {
        if (signInTab) signInTab.location.href = result.authorization_url;
        else if (showControlRef.current) setNotice({ title: "Sign-in page blocked", message: "Your browser blocked the AWS sign-in tab. Select Open sign-in page in the top bar to continue.", tone: "warning" });
      } else {
        signInTab?.close();
        if (showControlRef.current) setNotice(builderIdNotice(result.state, result.failure_reason));
      }
    } catch (reason) {
      signInTab?.close();
      updateStatus({ state: "sign_in_failed" });
      if (showControlRef.current) setNotice({ title: "Sign-in unavailable", message: safeErrorMessage(reason instanceof ApiError ? reason.kind : "auth"), tone: "danger" });
    }
  }

  const state = status.state;
  return <div className={showControl ? "auth-control" : "auth-control-idle"}>
    {showControl && (state === "not_connected" || state === "sign_in_failed" ?
      <button type="button" className="auth-control-button" onClick={signIn}><Icon name="shield" size={13} />{builderIdLabel(state)}</button> :
      <span role="status" className={`auth-control-status ${state === "registration_required" || state === "access_unavailable" ? "warning" : state === "live_aws" ? "connected" : ""}`}><span aria-hidden="true" className="auth-indicator" />{state === "live_aws" && mode === "demo" ? "Builder ID connected" : builderIdLabel(state)}</span>)}
    {showControl && state === "connecting" && (authorizationUrl ?
      <a className="auth-control-reopen" href={authorizationUrl} target="_blank" rel="noopener noreferrer">Open sign-in page</a> :
      <button type="button" className="auth-control-reopen" onClick={signIn}>Open sign-in page</button>)}
    <dialog ref={dialogRef} className="auth-dialog" aria-labelledby="auth-dialog-title" aria-describedby="auth-dialog-message" onClose={() => setNotice(null)}>
      {notice && <div className="auth-dialog-content">
        <div className={`auth-dialog-mark ${notice.tone}`} aria-hidden="true"><Icon name="shield" size={20} /></div>
        <div className="eyebrow">AWS BUILDER ID</div>
        <h2 id="auth-dialog-title" className="auth-dialog-title">{notice.title}</h2>
        <p id="auth-dialog-message" className="auth-dialog-message">{notice.message}</p>
        <div className="auth-dialog-actions">
          <button type="button" className="button-secondary" onClick={() => { setNotice(null); onContinueDemo?.(); }}>Continue with demo</button>
          {state === "sign_in_failed" || state === "not_connected" || (state === "access_unavailable" && status.failure_reason === "authentication_failed") ? <button type="button" className="button-primary" onClick={signIn}>Try sign-in again</button> : null}
        </div>
      </div>}
    </dialog>
  </div>;
}
