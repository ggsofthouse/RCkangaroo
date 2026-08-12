# RTX 5090 cluster validation

No SSH keys, tokens, IP addresses, or Vast credentials are stored in Git.

## One host

```bash
git clone https://github.com/ggsofthouse/RCkangaroo.git /workspace/RCkangaroo-cluster
cd /workspace/RCkangaroo-cluster
chmod +x cluster/cluster_5090_node.sh
cluster/cluster_5090_node.sh benchmark 30 139 20 10
cluster/cluster_5090_node.sh p100-residue20 30 139 20 10
```

The first command benchmarks every GPU independently. The second runs one
RCKangaroo process over every GPU in that host and verifies the solved Puzzle
#100 reduced by 20 known bits. Results go to `/workspace/rck-cluster-results`.

## Several hosts from Windows

Copy `cluster_hosts.example.csv` to an untracked `cluster_hosts.csv`, fill in
each direct SSH endpoint, then run:

```powershell
.\cluster\dispatch_cluster_5090.ps1 `
  -HostsCsv .\cluster_hosts.csv `
  -KeyPath C:\Users\you\.ssh\vast_cluster_ed25519 `
  -Mode benchmark -Seconds 30 -InvSm 10
```

The dispatcher launches all hosts concurrently and downloads their archives.
Sum `average_mkeys_s` from the CSVs for aggregate hardware throughput.

Do not launch the same ECDLP target independently on several hosts and call it a
divided search. Use the existing pool coordinator for disjoint offsets/chunks.
Simple interval slicing across `m` independent nodes provides roughly `sqrt(m)`
algorithmic wall-clock speedup, not `m`; a coherent shared Kangaroo/DP state is a
different distributed algorithm.
