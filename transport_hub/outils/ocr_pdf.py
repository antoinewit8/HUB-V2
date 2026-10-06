import streamlit as st
import tempfile
import os
import subprocess
from pathlib import Path

from core import ui

ui.page("ocr", "Deux outils indépendants pour vos PDF scannés : texte sélectionnable, ou lisibilité améliorée.")

# ─── Imports ─────────────────────────────────────────────────────────────────
try:
    from pdf2image import convert_from_bytes
    from PIL import Image, ImageEnhance, ImageFilter
    import img2pdf
    import ocrmypdf
except ImportError as e:
    st.error(f"Dépendance manquante : `{e}`")
    st.stop()

# ─── Langues disponibles ─────────────────────────────────────────────────────
def get_available_langs() -> list[str]:
    try:
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10)
        lines = result.stdout.strip().splitlines()
        return sorted([l.strip() for l in lines if l.strip() and not l.startswith("List") and l.strip() != "osd"])
    except Exception:
        return ["fra", "eng"]

LANG_LABELS = {
    "fra": "Français", "eng": "Anglais", "deu": "Allemand",
    "nld": "Néerlandais", "spa": "Espagnol", "ita": "Italien",
}
available_langs = get_available_langs()
lang_options = {LANG_LABELS.get(l, l): l for l in available_langs}

# ─── Titre ───────────────────────────────────────────────────────────────────

tab_ocr, tab_enhance = st.tabs(["OCR — Texte sélectionnable", "Amélioration visuelle"])


# ════════════════════════════════════════════════════════════════════════════
# ONGLET 1 — OCR
# ════════════════════════════════════════════════════════════════════════════
with tab_ocr:

    st.markdown("""
    <div class="ap-card">
    <h4>À quoi ça sert ?</h4>
    Votre PDF scanné est une image — le texte n'est pas sélectionnable ni modifiable dans Adobe.<br>
    L'OCR ajoute une <strong>couche texte invisible</strong> par-dessus le scan : vous pourrez ensuite
    sélectionner, copier et modifier le texte directement dans <strong>Adobe Acrobat</strong>.
    </div>
    """, unsafe_allow_html=True)

    uploaded_ocr = st.file_uploader(
        "Chargez votre PDF scanné",
        type=["pdf"],
        key="upload_ocr",
        help="PDF dont le texte n'est pas sélectionnable"
    )

    if not uploaded_ocr:
        st.info("Chargez un PDF pour démarrer l'OCR")
    else:
        st.success(f"**{uploaded_ocr.name}** — {uploaded_ocr.size / 1024:.0f} Ko")
        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            if lang_options:
                selected_label = st.selectbox("Langue du document", list(lang_options.keys()), key="lang_ocr")
                selected_lang = lang_options[selected_label]
            else:
                selected_lang = "fra"
            deskew    = st.checkbox("Redresser les pages penchées", value=True, key="deskew_ocr")
            rotate    = st.checkbox("Correction automatique de l'orientation", value=False, key="rotate_ocr")
            force_ocr = st.checkbox("Forcer l'OCR (texte déjà présent)", value=False, key="force_ocr")

        with col2:
            output_type = st.selectbox("Format de sortie", ["pdfa", "pdf", "pdfa-2", "pdfa-3"],
                                       index=0, key="output_ocr",
                                       help="PDF/A recommandé pour l'archivage long terme")
            sidecar = st.checkbox("Générer un fichier texte (.txt)", value=False, key="sidecar_ocr",
                                  help="Exporte le texte OCR extrait en fichier séparé")

        st.divider()

        if st.button("Lancer l'OCR", type="primary", key="btn_ocr"):
            pdf_bytes   = uploaded_ocr.read()
            output_name = Path(uploaded_ocr.name).stem + "_OCR.pdf"
            progress    = st.progress(0, text="Préparation…")
            status_box  = st.empty()

            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    input_path   = os.path.join(tmpdir, "input.pdf")
                    output_path  = os.path.join(tmpdir, "output.pdf")
                    sidecar_path = os.path.join(tmpdir, "sidecar.txt") if sidecar else None

                    with open(input_path, "wb") as f:
                        f.write(pdf_bytes)

                    progress.progress(20, text="OCR en cours…")

                    exit_code = ocrmypdf.ocr(
                        input_path,
                        output_path,
                        language=[selected_lang],
                        deskew=deskew,
                        rotate_pages=rotate,
                        output_type=output_type,
                        optimize=0,
                        force_ocr=force_ocr,
                        sidecar=sidecar_path,
                        progress_bar=False,
                    )

                    progress.progress(90, text="Finalisation…")

                    if exit_code == ocrmypdf.ExitCode.ok:
                        with open(output_path, "rb") as f:
                            result_bytes = f.read()

                        sidecar_text = ""
                        if sidecar_path and os.path.exists(sidecar_path):
                            with open(sidecar_path, "r", encoding="utf-8", errors="ignore") as f:
                                sidecar_text = f.read()

                        progress.progress(100, text="OCR terminé !")
                        status_box.success("OCR terminé — le texte est maintenant sélectionnable dans Adobe.")

                        st.divider()
                        m1, m2, m3 = st.columns(3)
                        orig_ko   = len(pdf_bytes) / 1024
                        result_ko = len(result_bytes) / 1024
                        delta     = result_ko - orig_ko
                        sign      = "+" if delta > 0 else ""
                        m1.metric("Taille originale", f"{orig_ko:.0f} Ko")
                        m2.metric("Taille OCRisée",   f"{result_ko:.0f} Ko", delta=f"{sign}{delta:.0f} Ko")
                        m3.metric("Langue utilisée",  selected_label)

                        st.download_button(
                            "⬇️ Télécharger le PDF OCRisé",
                            data=result_bytes,
                            file_name=output_name,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                        )

                        if sidecar_text.strip():
                            with st.expander("Aperçu du texte extrait", expanded=False):
                                st.text_area("Texte OCR",
                                             value=sidecar_text[:5000] + ("…" if len(sidecar_text) > 5000 else ""),
                                             height=300)
                                st.download_button(
                                    "⬇️ Télécharger le texte (.txt)",
                                    data=sidecar_text.encode("utf-8"),
                                    file_name=Path(uploaded_ocr.name).stem + "_texte.txt",
                                    mime="text/plain",
                                )
                    else:
                        status_box.error(f"OCRmyPDF a retourné le code : {exit_code}")

            except ocrmypdf.exceptions.PriorOcrFoundError:
                progress.empty()
                st.warning("Ce PDF contient déjà une couche texte. Activez **'Forcer l'OCR'**.")
            except ocrmypdf.exceptions.MissingDependencyError as e:
                progress.empty()
                st.error(f"Dépendance manquante : {e}")
            except Exception as e:
                progress.empty()
                st.error(f"Erreur : {e}")
                raise e


# ════════════════════════════════════════════════════════════════════════════
# ONGLET 2 — AMÉLIORATION VISUELLE
# ════════════════════════════════════════════════════════════════════════════
with tab_enhance:

    st.markdown("""
    <div class="ap-card">
    <h4>À quoi ça sert ?</h4>
    Améliore la <strong>qualité visuelle</strong> d'un scan flou, sombre ou peu lisible.<br>
    Agit sur le contraste, la luminosité et la netteté de chaque page.<br>
    Optionnellement, ajoute aussi la couche OCR sur le PDF amélioré.
    </div>
    """, unsafe_allow_html=True)

    uploaded_enh = st.file_uploader(
        "Chargez votre PDF scanné",
        type=["pdf"],
        key="upload_enh",
        help="PDF flou, sombre ou avec écriture peu lisible"
    )

    if not uploaded_enh:
        st.info("Chargez un PDF pour démarrer l'amélioration")
    else:
        st.success(f"**{uploaded_enh.name}** — {uploaded_enh.size / 1024:.0f} Ko")
        st.divider()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Filtres image**")
            contrast   = st.slider("Contraste",  0.5, 3.0, 1.8, 0.1, key="contrast_enh",
                                   help="1.0 = original · >1.5 recommandé pour scans pâles")
            sharpness  = st.slider("Netteté",    0.5, 3.0, 2.0, 0.1, key="sharp_enh",
                                   help="1.0 = original · >2.0 pour scans flous")
            brightness = st.slider("Luminosité", 0.5, 2.0, 1.1, 0.1, key="bright_enh",
                                   help="1.0 = original · >1.2 pour scans sombres")
            grayscale  = st.checkbox("Convertir en niveaux de gris", value=False, key="gray_enh",
                                     help="Recommandé pour les documents N&B — réduit le poids")

        with col2:
            st.markdown("**Rendu**")
            dpi          = st.select_slider("Résolution (DPI)", options=[150, 200, 300, 400],
                                            value=300, key="dpi_enh",
                                            help="300 = recommandé · 400 = qualité max (plus lent)")
            jpeg_quality = st.slider("Qualité JPEG", 70, 100, 92, 1, key="jpeg_enh",
                                     help="92 = bon équilibre · 100 = qualité max")

        with col3:
            st.markdown("**OCR optionnel**")
            do_ocr_enh = st.checkbox("Ajouter couche OCR après amélioration", value=False, key="ocr_enh",
                                     help="Rend le PDF résultant cherchable et modifiable dans Adobe")
            if do_ocr_enh and lang_options:
                selected_label_enh = st.selectbox("Langue", list(lang_options.keys()), key="lang_enh")
                selected_lang_enh  = lang_options[selected_label_enh]
            else:
                selected_lang_enh = "fra"

        st.divider()

        with st.expander("Conseils selon votre type de scan"):
            st.markdown("""
| Problème | Contraste | Luminosité | Netteté | Autre |
|---|---|---|---|---|
| Scan pâle / délavé | **2.5** | 1.1 | 2.0 | — |
| Scan sombre | 1.8 | **1.4** | 2.0 | — |
| Scan flou | 1.8 | 1.1 | **2.5** | — |
| Fond grisâtre | **2.2** | 1.0 | 1.8 | — |
| Document N&B | 2.0 | 1.0 | 2.0 | ✅ Niveaux de gris |
""")

        if st.button("Lancer l'amélioration", type="primary", key="btn_enh"):
            pdf_bytes   = uploaded_enh.read()
            output_name = Path(uploaded_enh.name).stem + "_ameliore.pdf"
            progress    = st.progress(0, text="Lecture du PDF…")
            status_box  = st.empty()

            try:
                with tempfile.TemporaryDirectory() as tmpdir:

                    # ── Conversion PDF → images ─────────────────────────────
                    progress.progress(10, text="Conversion en images…")
                    pages = convert_from_bytes(pdf_bytes, dpi=dpi)
                    total_pages = len(pages)
                    status_box.info(f"{total_pages} page(s) à traiter")

                    image_paths = []
                    for i, page in enumerate(pages):
                        pct = 10 + int((i / total_pages) * 55)
                        progress.progress(pct, text=f"Amélioration page {i+1}/{total_pages}…")

                        if grayscale:
                            page = page.convert("L").convert("RGB")
                        page = ImageEnhance.Contrast(page).enhance(contrast)
                        page = ImageEnhance.Brightness(page).enhance(brightness)
                        page = ImageEnhance.Sharpness(page).enhance(sharpness)
                        if sharpness >= 2.0:
                            page = page.filter(ImageFilter.SHARPEN)

                        img_path = os.path.join(tmpdir, f"page_{i:04d}.jpg")
                        page.save(img_path, "JPEG", quality=jpeg_quality, optimize=True)
                        image_paths.append(img_path)

                    # ── Recompilation PDF ───────────────────────────────────
                    progress.progress(68, text="Recompilation du PDF…")
                    enhanced_pdf_path = os.path.join(tmpdir, "enhanced.pdf")
                    with open(enhanced_pdf_path, "wb") as f:
                        f.write(img2pdf.convert(image_paths))

                    # ── OCR optionnel ───────────────────────────────────────
                    if do_ocr_enh:
                        progress.progress(78, text="OCR en cours…")
                        output_path = os.path.join(tmpdir, "output.pdf")
                        ocrmypdf.ocr(
                            enhanced_pdf_path,
                            output_path,
                            language=[selected_lang_enh],
                            deskew=False,
                            optimize=0,
                            force_ocr=True,
                            progress_bar=False,
                        )
                        final_path = output_path
                    else:
                        final_path = enhanced_pdf_path

                    # ── Résultat ────────────────────────────────────────────
                    progress.progress(95, text="Finalisation…")
                    with open(final_path, "rb") as f:
                        result_bytes = f.read()

                    progress.progress(100, text="Terminé !")
                    status_box.success("Amélioration terminée !")

                    st.divider()
                    m1, m2, m3 = st.columns(3)
                    orig_ko   = len(pdf_bytes) / 1024
                    result_ko = len(result_bytes) / 1024
                    delta     = result_ko - orig_ko
                    sign      = "+" if delta > 0 else ""
                    m1.metric("Pages traitées",   f"{total_pages}")
                    m2.metric("Taille originale", f"{orig_ko:.0f} Ko")
                    m3.metric("Taille finale",    f"{result_ko:.0f} Ko", delta=f"{sign}{delta:.0f} Ko")

                    st.download_button(
                        "⬇️ Télécharger le PDF amélioré",
                        data=result_bytes,
                        file_name=output_name,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True,
                    )

            except Exception as e:
                progress.empty()
                st.error(f"Erreur : {e}")
                raise e
