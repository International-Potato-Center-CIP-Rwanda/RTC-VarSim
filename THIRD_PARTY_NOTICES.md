# Third-party software

AFSA–VarScout adapts the static similarity method from the WebAFSA source supplied through https://github.com/izuku-franck1555/AFSA-Maize-land-suitability-Tanzania.

The retained upstream files are covered by the MIT license, copyright (c) 2024 Tonle Franck. The complete notice is preserved in `upstream/LICENSE`. Archive and source hashes are recorded in `PROVENANCE.json`. Preserve these notices with redistributed copies or substantial portions of the upstream software.

Leaflet is bundled under its existing license in `assets/leaflet/LICENSE`.

The locally generated extraction mask derives from geoBoundaries CGAZ (https://www.geoboundaries.org/), CC BY 4.0. Attribution: Runfola, D. et al. (2020), geoBoundaries: A global database of political administrative boundaries, PLoS ONE 15(4): e0231866, https://doi.org/10.1371/journal.pone.0231866. Processing selects African features and regional island geometries, repairs invalid geometries, and assigns the verified WGS84 CRS without modifying the original user file. Source hashes and selections are stored beside the local mask. No additional simplification is applied; the source CGAZ product itself is generalized.

The proposed root LICENSE covers original software contributions under MIT, subject to confirmation by their rights holders. It does not grant rights to the local catalogue, CIP branding or geospatial datasets. The project is a research prototype and is not presented as an officially endorsed CIP product.

## Rwanda potato reference

Borus, D.; Mendes, T.; Ndacyayisenga, T.; Nduwayezu, A.; Niragire, I.; Niyonteze, G.; Nshimiyimana, J. C.; Uzamushaka, S. (2025). *Rwanda Potato Variety Description Guide*. International Potato Center. [DOI 10.4160/cip.2025.03.001](https://doi.org/10.4160/cip.2025.03.001). Copyright 2025 International Potato Center, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The guide PDF and JSON extraction are external local inputs, not included in this public source-only release. The software supports page-referenced records and explicit source discrepancies. This does not authorize distribution of the separate internal RAB catalogue or unpublished trial data.

## Documentation changes for v1.0.0 preparation

The retained upstream Python files have received documentation-only module and function docstrings. Their executable ASTs are unchanged. PROVENANCE.json preserves the hashes of the source archive and original supplied files; those historical hashes are not the hashes of the annotated release files. RELEASE_MANIFEST.txt lists the prepared file hashes. The full MIT notice in upstream/LICENSE is unchanged.
