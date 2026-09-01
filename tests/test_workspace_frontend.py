from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "reyes_agent" / "static"


def _run_node_module(module_name: str, script: str) -> dict:
    source = (STATIC / "workspace" / module_name).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / module_name.replace(".js", ".mjs")
        if module_name == "shell.js":
            client = (STATIC / "workspace" / "client.js").read_text(encoding="utf-8")
            (Path(directory) / "client.mjs").write_text(client, encoding="utf-8")
            source = source.replace("./client.js", "./client.mjs")
        target.write_text(source, encoding="utf-8")
        runner = Path(directory) / "runner.mjs"
        runner.write_text(
            f"import * as subject from {json.dumps(target.as_uri())};\n{script}",
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["node", str(runner)], capture_output=True, text=True, check=True, timeout=20)
        return json.loads(completed.stdout.strip())


def test_revision_buffer_orders_events_and_rehydrates_on_gap() -> None:
    output = _run_node_module("client.js", """
      const b = new subject.WorkspaceRevisionBuffer();
      b.pushEvent({type:'workspace.panel.changed', payload:{revision:5, panel:{panel_id:'system', instance_id:'system', state:'ACTIVE'}}});
      b.applySnapshot({revision:4, panels:[], activities:[], history:[], health:[]});
      const afterBuffered = {revision:b.revision, panels:b.state.panels.length};
      b.pushEvent({type:'workspace.activity.changed', payload:{revision:7, activity:{activity_id:'a1'}}});
      const afterGap = {revision:b.revision, gap:b.needsRehydrate};
      b.applySnapshot({revision:7, panels:[], activities:[{activity_id:'a1'}], history:[], health:[]});
      const staleAccepted = b.pushEvent({type:'workspace.panel.changed', payload:{revision:6}});
      console.log(JSON.stringify({afterBuffered, afterGap, finalRevision:b.revision, staleAccepted}));
    """)

    assert output == {
        "afterBuffered": {"revision": 5, "panels": 1},
        "afterGap": {"revision": 5, "gap": True},
        "finalRevision": 7,
        "staleAccepted": False,
    }


def test_headless_shell_hydrates_and_delegates_actions_without_polling() -> None:
    output = _run_node_module("shell.js", """
      globalThis.requestAnimationFrame = (fn) => { fn(); return 1; };
      const calls = [];
      const fetchImpl = async (url, options={}) => {
        calls.push({url:String(url), method:options.method || 'GET'});
        const body = String(url).includes('/search')
          ? {revision:1, results:[{id:'panel:system', kind:'panel', action:'show', target:'system'}]}
          : {revision:1, panels:[], panel_definitions:[], commands:[], activities:[], history:[], health:[]};
        return {ok:true, json:async()=>body};
      };
      const shell = subject.createWorkspaceShell({fetchImpl, documentRef:null});
      await shell.hydrate();
      await shell.panelAction('system', 'show');
      const results = await shell.search('system');
      await shell.executeSearchResult(results[0]);
      shell.dispose();
      console.log(JSON.stringify({calls, methods:Object.keys(shell).sort()}));
    """)

    urls = [row["url"] for row in output["calls"]]
    assert urls.count("/api/workspace/state") >= 1
    assert urls.count("/api/workspace/panels/system/show") == 2
    assert any(url.startswith("/api/workspace/search?q=system") for url in urls)
    assert {"consumeEvent", "dispose", "executeSearchResult", "hydrate",
            "panelAction", "search"} <= set(output["methods"])


def test_dashboard_wires_workspace_to_existing_stream_and_remote_palette() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    shell = (STATIC / "workspace" / "shell.js").read_text(encoding="utf-8")

    assert page.count("new EventSource('/api/events/stream')") == 1
    assert "/static/workspace/shell.js" in page
    assert "/static/workspace/styles.css" in page
    assert "consumeEvent(update)" in page
    assert "dashboardEvents.onopen" in page and ".hydrate()" in page
    assert "workspaceSearchAbort" in page and "workspaceSearchSequence" in page
    assert "executeSearchResult" in page
    assert "setInterval" not in shell
    assert "requestAnimationFrame" in shell


def test_activity_view_updates_event_state_without_auto_opening() -> None:
    source = (STATIC / "activity_view.js").read_text(encoding="utf-8")
    consume = source[source.index("function consumeEvent(update)"):
                     source.index("async function refresh()")]
    refresh = source[source.index("async function refresh()"):
                     source.index("function openWebsiteStudio()")]

    assert "show()" not in consume
    assert "show()" not in refresh
    assert "overlay.classList.contains('open')" in consume

