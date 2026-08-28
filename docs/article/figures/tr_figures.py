"""Figures for the Turkish article.

Not translations of the English set. That article is written for someone who
will go and read the code; this one is written for someone deciding whether the
idea is worth their afternoon. So these are fewer, flatter and carry less: the
sequence diagram becomes a numbered timeline, the architecture loses its audit
column and its bypass routes, and the refusal strings come out entirely.

Same palette and same primitives as the English set, so the two articles look
like they came from the same desk.
"""

from __future__ import annotations

from _theme import (
    AMBER,
    AMBER_FILL,
    FAINT,
    INK,
    LINE,
    MUTED,
    PAGE,
    PANEL,
    RED,
    RED_FILL,
    SLATE,
    SLATE_EDGE,
    SLATE_FILL,
    TEAL,
    TEAL_EDGE,
    TEAL_FILL,
    VIOLET,
    VIOLET_EDGE,
    VIOLET_FILL,
    Canvas,
    title,
)

# ---------------------------------------------------------------------------
# 1. The shape of the system
# ---------------------------------------------------------------------------


def katmanlar() -> Canvas:
    page_w, page_h = 1000, 940
    mx, mw = 40, 920
    mid = mx + mw / 2
    c = Canvas(page_w, page_h)

    title(
        c,
        mx,
        46,
        "Sistemin kabaca şekli",
        "Yeşil kutular kod. Mor kutu, ikna edilebilen tek yer.",
    )

    def band(y, h, heading, *, accent, fill, edge, dash=None):
        c.box(mx, y, mw, h, fill=fill, stroke=edge, width=1.8, radius=12, dash=dash)
        c.text(mx + 18, y + 24, heading, size=11.5, fill=accent, bold=True, spacing=0.9)

    def chips(y, labels, *, ink, edge, size=13, h=36):
        n = len(labels)
        gap = 12
        w = (mw - 36 - gap * (n - 1)) / n
        for i, label in enumerate(labels):
            x = mx + 18 + i * (w + gap)
            c.box(x, y, w, h, fill=PAGE, stroke=edge, width=1.3, radius=7)
            c.text(x + w / 2, y + h / 2 + size * 0.35, label, size=size, anchor="middle", fill=ink)

    y = 104
    c.label_box(
        mx + 300,
        y,
        mw - 600,
        50,
        [("Müşterinin mesajı", {"size": 15, "bold": True})],
        fill=PANEL,
        stroke=LINE,
    )
    c.text(
        mid, y + 68, "güvenilmez kabul edilir", size=12, fill=MUTED, anchor="middle", italic=True
    )
    c.line(mid, y + 76, mid, y + 96, arrow="a")
    y += 96

    band(y, 100, "FİLTRELER", accent=TEAL, fill=TEAL_FILL, edge=TEAL_EDGE)
    chips(
        y + 44,
        ["yazıyı sadeleştir", "kimlik bilgilerini maskele", "talimat ara", "çite al"],
        ink=TEAL,
        edge=TEAL_EDGE,
        size=12.5,
    )
    c.line(mid, y + 100, mid, y + 128, arrow="a")
    y += 128

    band(y, 104, "MODEL", accent=VIOLET, fill=VIOLET_FILL, edge=VIOLET_EDGE, dash="6 4")
    c.text(mid, y + 58, "Ne yapılması gerektiğini önerir.", size=15, fill=INK, anchor="middle")
    c.text(
        mid, y + 82, "Karar vermez, uygulamaz.", size=15, fill=VIOLET, anchor="middle", bold=True
    )
    c.line(mid, y + 104, mid, y + 132, arrow="a")
    y += 132

    band(y, 116, "KURALLAR", accent=TEAL, fill=TEAL_FILL, edge=TEAL_EDGE)
    c.text(
        mid,
        y + 52,
        "18 kural, her biri dayandığı politika maddesini yazarak karar verir",
        size=13.5,
        fill=INK,
        anchor="middle",
    )
    for cx, label, colour, bg in (
        (mx + 200, "İZİN VAR", TEAL, TEAL_FILL),
        (mid, "İNSANA SOR", AMBER, AMBER_FILL),
        (mx + mw - 200, "RET", RED, RED_FILL),
    ):
        c.pill(cx, y + 66, label, size=12.5, fill=bg, stroke=colour, ink=colour, bold=True)
    c.line(mid, y + 116, mid, y + 144, arrow="a")
    y += 144

    band(y, 100, "YETENEK SINIRI", accent=TEAL, fill=TEAL_FILL, edge=TEAL_EDGE)
    chips(
        y + 44,
        ["acil durdurma", "yetki", "hız limiti", "tekrar koruması", "onay"],
        ink=TEAL,
        edge=TEAL_EDGE,
        size=12,
    )
    c.line(mid, y + 100, mid, y + 128, arrow="a")
    y += 128

    band(y, 100, "ARAÇLAR", accent=SLATE, fill=SLATE_FILL, edge=SLATE_EDGE)
    labels = ["sipariş", "kargo", "katalog", "politika", "ödeme"]
    n = len(labels)
    w = (mw - 36 - 12 * (n - 1)) / n
    for i, label in enumerate(labels):
        x = mx + 18 + i * (w + 12)
        para = label == "ödeme"
        c.box(
            x,
            y + 42,
            w,
            40,
            fill=RED_FILL if para else PAGE,
            stroke=RED if para else SLATE_EDGE,
            width=1.6 if para else 1.3,
            radius=7,
        )
        c.text(
            x + w / 2,
            y + 42 + (18 if para else 24),
            label,
            size=12.5,
            anchor="middle",
            fill=RED if para else SLATE,
            bold=para,
        )
        if para:
            c.text(x + w / 2, y + 42 + 32, "para hareket eder", size=10, anchor="middle", fill=RED)
    y += 124

    c.box(mx, y, mw, 62, fill=PANEL, stroke=LINE, width=1.6, radius=10)
    c.text(
        mid,
        y + 26,
        "Mor kutudan paraya giden her yol iki yeşil kutudan geçer.",
        size=14.5,
        fill=INK,
        anchor="middle",
        bold=True,
    )
    c.text(
        mid,
        y + 48,
        "Model tamamen ikna olsa bile, izni veren o değil.",
        size=13,
        fill=MUTED,
        anchor="middle",
    )

    c.text(
        page_w - 40,
        page_h - 16,
        "backstop-governed-agents",
        size=11.5,
        fill=FAINT,
        anchor="end",
        mono=True,
    )
    return c


# ---------------------------------------------------------------------------
# 2. The five checks
# ---------------------------------------------------------------------------


def kontroller() -> Canvas:
    page_w, page_h = 940, 660
    mx, mw = 40, 860
    c = Canvas(page_w, page_h)

    title(
        c,
        mx,
        46,
        "Paraya giden yoldaki beş kontrol",
        "Her seferinde, bu sırayla, kim isterse istesin.",
    )

    kontrol = [
        ("Acil durdurma", "Sistem komple durduruldu mu?"),
        ("Yetki", "Bu çağrıyı yapan tarafın ödeme yetkisi var mı?"),
        ("page_hız limiti", "Kısa sürede aynı işlemi kaç kez denedi?"),
        ("Tekrar koruması", "Bu çağrı zaten çalıştı mı?"),
        ("Onay", "Tam olarak bu çağrı için imzalı bir onay var mı?"),
    ]

    y = 108
    row_h, gap = 74, 12
    for i, (name, soru) in enumerate(kontrol):
        ry = y + i * (row_h + gap)
        c.box(mx, ry, mw, row_h, fill=TEAL_FILL, stroke=TEAL_EDGE, width=1.7, radius=10)
        c.box(mx + 18, ry + 21, 32, 32, fill=TEAL, stroke=TEAL, radius=16)
        c.text(mx + 34, ry + 32, str(i + 1), size=14, fill=PAGE, anchor="middle", bold=True)
        c.text(mx + 66, ry + 31, name, size=15.5, fill=TEAL, bold=True)
        c.text(mx + 66, ry + 53, soru, size=13, fill=MUTED)
        if i < len(kontrol) - 1:
            c.line(mx + mw / 2, ry + row_h, mx + mw / 2, ry + row_h + gap, stroke=TEAL, width=1.6)

    y += 5 * (row_h + gap) + 8
    c.box(mx, y, mw, 66, fill=PANEL, stroke=LINE, width=1.6, radius=10)
    c.text(
        mx + mw / 2,
        y + 28,
        "Hiçbiri müşterinin mesajını okumaz.",
        size=15,
        fill=INK,
        anchor="middle",
        bold=True,
    )
    c.text(
        mx + mw / 2,
        y + 50,
        "Bu yüzden hiçbiri ikna edilemez, kandırılamaz, yeni bir şirket politikasından haberdar edilemez.",
        size=12.5,
        fill=MUTED,
        anchor="middle",
    )

    c.text(
        page_w - 40,
        page_h - 16,
        "backstop-governed-agents",
        size=11.5,
        fill=FAINT,
        anchor="end",
        mono=True,
    )
    return c


# ---------------------------------------------------------------------------
# 3. One refund, as a timeline
# ---------------------------------------------------------------------------


def yolculuk() -> Canvas:
    page_w, page_h = 960, 960
    mx = 40
    rail = mx + 26
    tx = mx + 74
    c = Canvas(page_w, page_h)

    title(
        c,
        mx,
        46,
        "Bir iadenin yolculuğu",
        "Tavanın üstünde bir tutar. Sistem duruyor, insan karar veriyor, para bir kez çıkıyor.",
    )

    adim = [
        (
            VIOLET,
            "Model öneriyor",
            ["Müşterinin anlattığına ve sipariş kayıtlarına bakıp", "590,27'lik bir iade önerir."],
        ),
        (
            TEAL,
            "Kurallar bakıyor",
            ["Bu müşteri kademesinde otomatik onay tavanı 75.", "Karar: insana sor."],
        ),
        (
            RED,
            "Ajan yine de deniyor",
            [
                "Ve reddediliyor: elinde bu çağrı için bir onay yok.",
                "Reddedilme, başarılı işlemler kadar ayrıntılı kayda geçiyor.",
            ],
        ),
        (
            AMBER,
            "Sistem duruyor",
            [
                "İşlem olduğu yerde donuyor ve onay kuyruğuna düşüyor.",
                "Bu bekleme günlerce sürebilir; kaldığı yerden devam eder.",
            ],
        ),
        (
            AMBER,
            "İnsan onaylıyor",
            [
                "Üretilen onay yalnızca bu çağrıya bağlıdır:",
                "bu talep, bu işlem, bu tutar. 75 onaylamak 590,27'yi açmaz.",
            ],
        ),
        (
            TEAL,
            "Para bir kez çıkıyor",
            [
                "İşlem tamamlanıyor. Ardından sistem çöküyor ve aynı çağrı",
                "tekrarlanıyor — ikinci bir ödeme yapılmıyor.",
            ],
        ),
    ]

    y = 116
    step = 124
    c.line(rail, y + 8, rail, y + (len(adim) - 1) * step + 8, stroke=LINE, width=2)

    for i, (colour, baslik, satirlar) in enumerate(adim):
        ay = y + i * step
        c.box(rail - 17, ay - 9, 34, 34, fill=colour, stroke=colour, radius=17)
        c.text(rail, ay + 12, str(i + 1), size=15, fill=PAGE, anchor="middle", bold=True)
        c.text(tx, ay + 8, baslik, size=17, fill=colour, bold=True)
        for j, satir in enumerate(satirlar):
            c.text(tx, ay + 38 + j * 21, satir, size=13.5, fill=INK)

    y = y + (len(adim) - 1) * step + 108
    c.box(mx, y, page_w - 80, 66, fill=PANEL, stroke=LINE, width=1.6, radius=10)
    c.text(
        mx + 22,
        y + 28,
        "Ajanın ikna olup olmadığı bu adımların hiçbirini değiştirmiyor.",
        size=14.5,
        fill=INK,
        bold=True,
    )
    c.text(
        mx + 22,
        y + 50,
        "Onay da, tekrar koruması da, kararın kendisi de modelin dışında duruyor.",
        size=13,
        fill=MUTED,
    )

    c.text(
        page_w - 40,
        page_h - 16,
        "backstop-governed-agents",
        size=11.5,
        fill=FAINT,
        anchor="end",
        mono=True,
    )
    return c


if __name__ == "__main__":
    for name, build in (
        ("tr1-katmanlar", katmanlar),
        ("tr2-kontroller", kontroller),
        ("tr3-yolculuk", yolculuk),
    ):
        print(build().save(name))
