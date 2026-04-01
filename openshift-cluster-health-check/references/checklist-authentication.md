# Authentication and OAuth Deep-Dive Diagnostics

Extended commands and signal patterns for Phase 5 of the OpenShift cluster health check.

---

## OAuth server detailed checks

```bash
# OAuth server pods and restarts
oc get pods -n openshift-authentication -l app=oauth-openshift -o wide
oc get pods -n openshift-authentication -l app=oauth-openshift \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}'

# OAuth server logs — look for errors
oc logs -n openshift-authentication -l app=oauth-openshift --tail=200 --prefix

# Authentication operator logs
oc logs -n openshift-authentication-operator \
  deployment/authentication-operator --tail=200
```

---

## Identity provider checks

```bash
# List configured identity providers
oc get oauth cluster -o jsonpath='{.spec.identityProviders}' | jq .

# Check OAuth routes are accessible
oc get route -n openshift-authentication

# Verify OAuth well-known endpoint (read-only, no credentials sent)
OAUTH_ROUTE=$(oc get route -n openshift-authentication -o jsonpath='{.items[0].spec.host}')
curl -sk "https://${OAUTH_ROUTE}/.well-known/oauth-authorization-server" | jq '.issuer'
```

---

## Token and session issues

```bash
# OAuthAccessToken count (high count can indicate token leak or long-lived sessions)
oc get oauthaccesstokens --no-headers 2>/dev/null | wc -l

# Check for expired or near-expired tokens (optional deep-dive)
oc get oauthaccesstokens -o json | \
  jq -r '.items[] | select(.expiresIn < 3600) | "\(.metadata.name)\texpires: \(.expiresIn)s"' | head -20
```

---

## Common failure patterns

| Symptom | Likely cause | Check |
|---|---|---|
| `oauth-openshift` pods in CrashLoopBackOff | Auth server config error or certificate issue | `oc logs` + `oc describe pod` |
| `authentication` operator Degraded | Misconfigured IdP or backend connectivity failure | `oc describe clusteroperator authentication` |
| Users see "login failed" in browser | Certificate mismatch on OAuth route | Inspect route TLS cert |
| `oc login` fails with TLS error | Expired or untrusted API server certificate | Phase 12 (certificates) |
| Existing sessions broken after cluster event | Cookie or token secret rotation | Check `openshift-authentication` secrets |
| Identity provider unreachable | Network policy, DNS, or IdP backend down | `oc get netnamespace`, DNS lookup |

---

## Certificate checks specific to OAuth

```bash
# OAuth serving certificate
oc get secret -n openshift-authentication-operator \
  -o json | jq -r '.items[] | select(.type=="kubernetes.io/tls") | .metadata.name'

# Check certificate expiry on the OAuth route secret
SECRET=$(oc get route -n openshift-authentication \
  -o jsonpath='{.items[0].spec.tls.secretName}' 2>/dev/null)
if [[ -n "$SECRET" ]]; then
  oc get secret -n openshift-authentication "$SECRET" \
    -o jsonpath='{.data.tls\.crt}' | base64 -d | \
    openssl x509 -noout -enddate 2>/dev/null
fi
```

---

## Events in the authentication namespace

```bash
oc get events -n openshift-authentication --sort-by=.lastTimestamp | tail -20
oc get events -n openshift-authentication-operator --sort-by=.lastTimestamp | tail -20
```
