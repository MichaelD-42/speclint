from speclint.readers import read

REQIF = """<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF xmlns="http://www.omg.org/spec/ReqIF/20110401/reqif.xsd" xmlns:xhtml="http://www.w3.org/1999/xhtml">
 <CORE-CONTENT><REQ-IF-CONTENT>
  <SPEC-TYPES><SPEC-OBJECT-TYPE IDENTIFIER="T1"><SPEC-ATTRIBUTES>
   <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="AD-TEXT" LONG-NAME="ReqIF.Text"/>
   <ATTRIBUTE-DEFINITION-STRING IDENTIFIER="AD-ID" LONG-NAME="ReqIF.ForeignID"/>
  </SPEC-ATTRIBUTES></SPEC-OBJECT-TYPE></SPEC-TYPES>
  <SPEC-OBJECTS>
   <SPEC-OBJECT IDENTIFIER="obj-1"><VALUES>
    <ATTRIBUTE-VALUE-STRING THE-VALUE="CUS-12"><DEFINITION><ATTRIBUTE-DEFINITION-STRING-REF>AD-ID</ATTRIBUTE-DEFINITION-STRING-REF></DEFINITION></ATTRIBUTE-VALUE-STRING>
    <ATTRIBUTE-VALUE-XHTML><DEFINITION><ATTRIBUTE-DEFINITION-XHTML-REF>AD-TEXT</ATTRIBUTE-DEFINITION-XHTML-REF></DEFINITION>
     <THE-VALUE><xhtml:div>The ECU shall <xhtml:b>start</xhtml:b> quickly.</xhtml:div></THE-VALUE></ATTRIBUTE-VALUE-XHTML>
   </VALUES></SPEC-OBJECT>
  </SPEC-OBJECTS>
 </REQ-IF-CONTENT></CORE-CONTENT>
</REQ-IF>"""

RST = """Requirements
============

.. req:: Start-up time
   :id: REQ_001
   :status: open

   The ECU shall start within 200 ms.

.. note:: not a need

.. spec:: Logging
   :id: SPEC_002

   Das Steuergerät muss Fehler
   speichern.
"""

MD = """# Requirements

```{req} Start-up time
:id: REQ_001

The ECU shall start within 200 ms.
```

- **CUS-7**: The ECU shall always be available.
SYS-3: Das Steuergerät muss jederzeit erreichbar sein.

Plain prose is ignored.
"""


def test_reqif(tmp_path):
    p = tmp_path / "a.reqif"
    p.write_text(REQIF, encoding="utf-8")
    [r] = read(p)
    assert (r.id, r.text) == ("CUS-12", "The ECU shall start quickly.")


def test_csv_semicolon_and_header_detection(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "ID;Anforderung;Status\nK-1;Das Steuergerät muss jederzeit erreichbar sein.;neu\nK-2;;neu\n",
        encoding="utf-8",
    )
    [r] = read(p)
    assert (r.id, r.text) == ("K-1", "Das Steuergerät muss jederzeit erreichbar sein.")


def test_csv_explicit_columns(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "Absolute Number,Object Heading,Main\n12,Head,The ECU shall start.\n",
        encoding="utf-8",
    )
    [r] = read(p, text_col="Main")
    assert (r.id, r.text) == ("12", "The ECU shall start.")


def test_rst_sphinx_needs(tmp_path):
    p = tmp_path / "a.rst"
    p.write_text(RST, encoding="utf-8")
    assert [(r.id, r.text) for r in read(p)] == [
        ("REQ_001", "The ECU shall start within 200 ms."),
        ("SPEC_002", "Das Steuergerät muss Fehler speichern."),
    ]


def test_markdown_myst_and_id_lines(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    assert [(r.id, r.text) for r in read(p)] == [
        ("REQ_001", "The ECU shall start within 200 ms."),
        ("CUS-7", "The ECU shall always be available."),
        ("SYS-3", "Das Steuergerät muss jederzeit erreichbar sein."),
    ]


def test_csv_cp1252_from_german_excel(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(
        "ID;Anforderung\nK-1;Das Steuergerät muss jederzeit erreichbar sein.\n".encode(
            "cp1252"
        )
    )
    [r] = read(p)
    assert r.text == "Das Steuergerät muss jederzeit erreichbar sein."


def test_csv_single_column(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "text\nThe ECU shall start quickly.\nThe ECU shall log errors.\n",
        encoding="utf-8",
    )
    assert [r.text for r in read(p)] == [
        "The ECU shall start quickly.",
        "The ECU shall log errors.",
    ]


def test_reqifz(tmp_path):
    import zipfile

    p = tmp_path / "a.reqifz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("export/a.reqif", REQIF)
    [r] = read(p)
    assert (r.id, r.text) == ("CUS-12", "The ECU shall start quickly.")


def test_reqifz_without_reqif_has_a_clear_error(tmp_path):
    import zipfile

    import pytest

    p = tmp_path / "a.reqifz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("readme.txt", "nothing")
    with pytest.raises(ValueError, match="no .reqif"):
        read(p)


def test_reqif_block_elements_keep_word_breaks(tmp_path):
    p = tmp_path / "a.reqif"
    p.write_text(
        REQIF.replace(
            "The ECU shall <xhtml:b>start</xhtml:b> quickly.",
            "<xhtml:p>The HMI shall show:</xhtml:p><xhtml:ul><xhtml:li>speed</xhtml:li>"
            "<xhtml:li>gear</xhtml:li></xhtml:ul>",
        ),
        encoding="utf-8",
    )
    [r] = read(p)
    assert r.text == "The HMI shall show: speed gear"


def test_reqif_inline_formatting_does_not_split_words(tmp_path):
    p = tmp_path / "a.reqif"
    p.write_text(
        REQIF.replace(
            "The ECU shall <xhtml:b>start</xhtml:b> quickly.",
            "Im <xhtml:b>Fehler</xhtml:b>fall muss das Steuergerät neu starten.",
        ),
        encoding="utf-8",
    )
    [r] = read(p)
    assert r.text == "Im Fehlerfall muss das Steuergerät neu starten."


def test_csv_with_a_short_row(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "ID;Text;Status\nK-1;Das Steuergerät muss starten.\n"
        "K-2;Das Steuergerät muss stoppen.;neu\n",
        encoding="utf-8",
    )
    assert [(r.id, r.text) for r in read(p)] == [
        ("K-1", "Das Steuergerät muss starten."),
        ("K-2", "Das Steuergerät muss stoppen."),
    ]


def test_csv_missing_id_cell_falls_back_to_row_number(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("Text;ID\nThe ECU shall start.\n", encoding="utf-8")
    [r] = read(p)
    assert r.id == "row 2"


def test_markdown_code_blocks_are_skipped(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(
        "Format:\n\n```text\nREQ-9: The ECU shall start quickly.\n```\n\n"
        "~~~\nREQ-8: Also an example.\n~~~\n\n"
        "- REQ-1: The ECU shall start within 200 ms.\n",
        encoding="utf-8",
    )
    assert [r.id for r in read(p)] == ["REQ-1"]


def test_markdown_longer_closing_fence_ends_the_block(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(
        "```\nREQ-9: example\n````\n\n"
        "````{req} Start\n:id: REQ_002\n\nThe ECU shall start.\n`````\n\n"
        "- REQ-1: The ECU shall start within 200 ms.\n",
        encoding="utf-8",
    )
    assert [r.id for r in read(p)] == ["REQ_002", "REQ-1"]
