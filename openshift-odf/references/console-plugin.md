# ODF Console Plugin

Use this runbook when the OpenShift Data Foundation UI is missing, the operator
**Console plugin** field is Disabled, or when enabling, verifying, or
troubleshooting `odf-console` / `odf-client-console` after a CLI OLM install.

A `ConsolePlugin` CR only *registers* a plugin. The web console loads the
intersection of available plugins and `console.operator.openshift.io/cluster`
`spec.plugins`. OperatorHub's **Enable console plugin** checkbox writes that
list; a CLI `Subscription` does not. After CLI install the CRs and pods are
usually already Running while **Storage → Data Foundation** is still absent.

`console.operator.openshift.io` is cluster-scoped. Do not patch it with
`-n openshift-storage` — the namespace is ignored and misleads operators into
thinking the Console lives beside the ODF CSV.

## Live Discovery

```bash
oc get consoleplugin
oc get console.operator.openshift.io cluster -o jsonpath='{.spec.plugins}{"\n"}'
oc -n openshift-storage get deploy odf-console ocs-client-operator-console
```

Classify before mutating:

| State | Evidence | Action |
|---|---|---|
| Operator not installed | no `odf-console` ConsolePlugin, no `odf-console` Deployment | install ODF first (`references/install-and-preflight.md`) |
| Installed, not enabled | CRs exist; names missing from `spec.plugins` | enable below |
| Already enabled | `odf-console` (and `odf-client-console` when that CR exists) is in `spec.plugins` | skip the patch; nothing to add. Refresh the browser |
| Pods not Ready | plugin is enabled but `odf-console` / `ocs-client-operator-console` is not Running | fix the Deployment; do not re-patch `spec.plugins` |

Enable `odf-client-console` when that ConsolePlugin CR exists (ODF 4.20+
`ocs-client-operator`). `odf-console` is what adds **Storage → Data Foundation**.

## Enable (keep every already-enabled plugin)

**Never replace `spec.plugins` with only `odf-console`.** The ODF 4.20
troubleshooting example that does this *replaces* the entire list and disables
`monitoring-plugin`, `networking-console-plugin`, and any other enabled plugin.

Do not run:

```bash
# NEVER replaces spec.plugins: oc patch console.operator cluster --type json -p '[{"op": "add", "path": "/spec/plugins", "value": ["odf-console"]}]'
```

Read the live list, merge, then patch the **full observed list**:

```bash
CURRENT=$(oc get console.operator.openshift.io cluster -o jsonpath='{.spec.plugins}')
[ -n "$CURRENT" ] || CURRENT='[]'

# Only enable plugins whose ConsolePlugin CR exists. The helper defaults to
# odf-console alone when --add is omitted; do not add odf-client-console unless
# that CR is present (otherwise you leave a stale name in spec.plugins).
ADD=(odf-console)
oc get consoleplugin odf-client-console >/dev/null 2>&1 && ADD+=(odf-client-console)

python3 scripts/render_console_plugin_patch.py \
  --current-plugins "$CURRENT" \
  --add "${ADD[@]}" \
  --output /tmp/odf-console-plugins.patch.json

# Review: the rendered spec.plugins MUST still contain every name from CURRENT.
cat /tmp/odf-console-plugins.patch.json
oc patch console.operator.openshift.io cluster --type merge \
  --patch-file /tmp/odf-console-plugins.patch.json
```

If you enable one plugin at a time instead of the helper, append with JSON
Pointer `/spec/plugins/-`. That path fails when `spec.plugins` is null; use the
helper merge in that case.

```bash
oc patch console.operator.openshift.io cluster --type json \
  -p '[{"op":"add","path":"/spec/plugins/-","value":"odf-console"}]'
oc patch console.operator.openshift.io cluster --type json \
  -p '[{"op":"add","path":"/spec/plugins/-","value":"odf-client-console"}]'
```

Appending a name that is already present creates a duplicate. If discovery
showed the plugin already enabled, skip; nothing to patch.

### From the UI

1. **Ecosystem → Installed Operators** (project `openshift-storage`)
2. **OpenShift Data Foundation** → Details → **Console plugin** → Enable → Save
3. When the console shows **Web console update is available**, click **Refresh web console**

## Validation

```bash
oc get console.operator.openshift.io cluster -o jsonpath='{.spec.plugins}{"\n"}'
oc -n openshift-storage get deploy odf-console ocs-client-operator-console
oc -n openshift-console get deploy console
```

- `spec.plugins` contains `odf-console` (and `odf-client-console` when that CR exists).
- Existing plugins from discovery are still present.
- After **Refresh web console**, **Storage → Data Foundation** is available.
- Console operator stays available; do not delete ConsolePlugin CRs to "toggle" — those are operator-owned. Disable by removing only that name from `spec.plugins` (see `scripts/render_console_plugin_patch.py --remove`). Full undeploy cleanup — prune `spec.plugins` **and** delete the ConsolePlugin CRs — is step 4a in `references/maintenance-uninstall.md`; both are cluster-scoped and survive namespace deletion.
