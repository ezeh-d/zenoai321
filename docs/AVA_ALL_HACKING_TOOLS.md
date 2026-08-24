# AVA AllHackingTools Integration

## Result

ZENO discovers the owner-supplied `AllHackingTools-main.zip` without trusting
or executing it. AVA exposes the catalog through `security_archive_catalog`.

The default source is:

```text
%USERPROFILE%\Downloads\AllHackingTools-main.zip
```

Set `ZENO_ALL_HACKING_TOOLS_ARCHIVE` to use another local archive.

## Why the archive is not installed directly

The bundle is a Termux/Linux installer menu containing self-modifying shell
scripts, network downloads, global package installation, destructive cleanup,
an embedded binary, and offensive projects with incompatible safety purposes.
Running its installer on Windows would neither produce a stable ZENO adapter nor
preserve the audited dependency environment.

ZENO instead:

1. Reads the ZIP directory without extraction.
2. Rejects absolute/traversal paths and bounded-size violations.
3. Computes the archive SHA-256 and caches by path, size, and modification time.
4. Parses the upstream tool manifest and classifies every referenced project.
5. Maps legitimate candidates to AVA's reviewed native catalog.
6. Requires an active owner-attested target scope before an active-testing route.
7. Keeps every archive script and binary non-executable.

## States

| State | Meaning |
|---|---|
| `DEFENSIVE_REFERENCE` | A defensive/diagnostic reference; use the reviewed ZENO-native equivalent. |
| `AUTHORIZED_TESTING` | May inform work only for an explicitly authorized target through AVA's normal gates. |
| `BLOCKED` | Deceptive, destructive, credential-stealing, privacy-invasive, spam or indiscriminate capability; never executed. |
| `QUARANTINED_INSTALLER` | Untrusted installer/script/binary; inventoried but never sourced, imported, extracted or launched. |
| `DOCUMENTATION` | Non-executable reference or asset. |

## AVA usage

Examples of safe requests:

```text
AVA, show me the AllHackingTools catalog.
AVA, list defensive tools in the archive.
AVA, why is Zphisher blocked?
AVA, show authorized-testing references related to SQL injection.
AVA, plan a web assessment of my authorized lab.
```

An active target must first pass the existing confirmation-gated
`security_authorize` attestation. Catalog access itself is read-only and does
not prove a tool is installed or authorize execution.

## Stability properties

- No startup import or background polling.
- No archive extraction or subprocess.
- No network call or automatic package installation.
- Bounded entry count, uncompressed size, manifest size and response length.
- Cached integrity/inventory results; cache invalidates when the archive changes.
- Errors return a truthful unavailable state without crashing AVA or ZENO.
