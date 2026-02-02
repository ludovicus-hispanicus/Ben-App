import spacy
from spacy_layout import spaCyLayout
import sys
import os
from PIL import Image, ImageDraw
from pdf2image import convert_from_path

def test_spacy_layout(pdf_path, output_dir="spacy_layout_results"):
    print(f"Testing spaCy Layout on: {pdf_path}")
    os.makedirs(output_dir, exist_ok=True)

    # 1. Load spaCy model (lightweight English model)
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("Downloading en_core_web_sm model...")
        from spacy.cli import download
        download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")

    # 2. Initialize Layout (this downloads the layout model if needed)
    layout = spaCyLayout(nlp)
    
    # 3. Process the PDF
    # spaCyLayout processes the whole PDF
    doc = layout(pdf_path)
    
    # 4. Visualize Results
    print("Generating visualizations...")
    try:
        images = convert_from_path(pdf_path)
    except Exception as e:
        print(f"Error converting PDF to images for visualization: {e}")
        return

    # Map spaCy pages to images
    # doc.spans["layout"] contains the layout elements
    
    for i, page_img in enumerate(images):
        draw = ImageDraw.Draw(page_img)
        page_no = i   # span page numbers are usually 0-indexed in spacy-layout? let's check.
                      # Standard spaCy layout usually maps layout spans to the text.
        
        print(f"Visualizing Page {i+1}...")
        
        # Iterate through layout spans
        if "layout" in doc.spans:
            for span in doc.spans["layout"]:
                # Check if span belongs to this page
                # spaCy layout spans usually have custom attributes for bounding boxes
                # The span._.layout_page attribute might exist, or we check the underlying tokens
                
                # Check custom extension attributes set by spacy-layout
                # Usually: span._.page_number, span._.x, span._.y, etc.
                # However, spacy-layout often provides 'layout' spans that wrap the text.
                
                # A safer way with the official library:
                # The library attaches bounding box info to the span.
                
                # Let's inspect the first span to see attributes if we were debugging, 
                # but here we'll use standard attributes often found in these plugins.
                
                # According to spacy-layout docs/code:
                # span._.bbox might be available, or we might need to access it differently.
                # Actually, spacy-layout stores page info.
                
                # Simplify: Inspect the structure using the layout object's internal data if possible,
                # or just iterate the spans and assume 1-1 mapping if simpler.
                
                # Let's try to access the layout info directly from the doc user data if available
                pass

        # Since specific API details for bounding box extraction from the doc object 
        # can vary by version, let's output the structure to JSON first so we can see what we have.
        
    # Serialize the layout data to JSON for inspection
    layout_data = []
    if "layout" in doc.spans:
        for span in doc.spans["layout"]:
            span_data = {
                "text": span.text[:50],
                "label": span.label_,
                "start": span.start,
                "end": span.end
            }
            # Try to grab extra attributes if they exist
            if span.has_extension("bbox"):
                span_data["bbox"] = span._.bbox
            if span.has_extension("page"):
                span_data["page"] = span._.page
            layout_data.append(span_data)

    import json
    with open(os.path.join(output_dir, "layout_structure.json"), "w", encoding="utf-8") as f:
        json.dump(layout_data, f, indent=2)

    print(f"Analysis complete. Structure saved to {output_dir}/layout_structure.json")
    print("Note: Detailed visualization requires confirming the specific attribute names for bounding boxes in this version of spacy-layout.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_spacy_layout.py <pdf_path>")
        sys.exit(1)
    
    test_spacy_layout(sys.argv[1])
