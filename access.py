"""外部からのアクセスの制限。許可されていない相手には、中身のない白いページだけを返す(図もAPIもMCPも見せない)。

目的は、ツールをサーバに置いただけで外部(インターネット)に公開されてしまうのを防ぐこと。通すのは次の相手だけ:
  1. このパソコン自身(127.0.0.1 / ::1)
  2. --allow で明示したIPアドレスの範囲(例: 192.168.1.0/24)。指定できるのは家庭・社内のネットワークの中だけ
nginx など同じパソコン上の中継サーバを通った場合は、中継サーバが伝える送信元(X-Real-IP / X-Forwarded-For の最後)で判定する。
"""
import ipaddress

BLANK = ('<!doctype html><html><head><meta charset="utf-8"><title></title></head>'
         '<body style="background:#fff"></body></html>')


# --allow で指定できるのは、家庭・社内のネットワーク(プライベートアドレス)の中だけ。
# インターネット側のアドレスや 0.0.0.0/0 は指定できないので、設定だけでは外部に公開できない
LOCAL_NETWORKS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",  # IPv4 のプライベートアドレス
    "169.254.0.0/16",                                 # IPv4 のリンクローカル
    "fc00::/7", "fe80::/10",                          # IPv6 のユニークローカル・リンクローカル
)]


def parse_allow(values):
    """--allow の値(カンマ区切り可・複数回可)を IP の範囲の一覧にする。家庭・社内のネットワーク以外は断る。"""
    nets = []
    for v in values or []:
        for part in str(v).split(","):
            if not part.strip():
                continue
            try:
                net = ipaddress.ip_network(part.strip(), strict=False)
            except ValueError:
                raise ValueError(f"--allow の値が IP アドレス(または 192.168.1.0/24 のような範囲)ではありません: {part.strip()}")
            if not any(net.version == p.version and net.subnet_of(p) for p in LOCAL_NETWORKS):
                raise ValueError(f"--allow に指定できるのは、家庭・社内のネットワーク(192.168.x.x / 10.x.x.x / 172.16〜31.x.x など)"
                                 f"の範囲だけです。インターネットに公開する設定はありません: {part.strip()}")
            nets.append(net)
    return nets


def _ip(text):
    try:
        ip = ipaddress.ip_address(str(text).strip().strip("[]"))
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


class Access:
    def __init__(self, allow=()):
        self.allow = list(allow)

    def describe(self):
        if not self.allow:
            return "このパソコンからだけ使えます。ほかの相手には白いページを返します"
        return "このパソコンと " + ", ".join(map(str, self.allow)) + " から使えます。ほかの相手には白いページを返します"

    def client_ip(self, remote, headers):
        ip = _ip(remote)
        if ip is not None and ip.is_loopback:
            # 同じパソコンの中継サーバ(nginx など)を通ってきた場合は、中継サーバが伝える本当の送信元で判定する。
            # X-Forwarded-For は先頭を利用者が偽れるので、中継サーバが最後に足したものを使う
            fwd = headers.get("X-Real-IP") or (headers.get("X-Forwarded-For") or "").split(",")[-1]
            if fwd.strip():
                return _ip(fwd)
        return ip

    def allowed(self, remote, headers):
        ip = self.client_ip(remote, headers)
        return ip is not None and (ip.is_loopback or any(ip in n for n in self.allow))
