import base64
import os
import sys

# Import the local OCR service
sys.path.append(os.path.join(os.path.dirname(__file__), 'server', 'src', 'services'))
import nemotron_ocr_service

def test_dynamic_slice(image_path):
    print(f"Loading image from {image_path}")
    
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    b64_img = base64.b64encode(img_bytes).decode("utf-8")
    
    print("Running Nemotron OCR to get bounding boxes...")
    # This will load the model if not loaded and process the image
    result = nemotron_ocr_service.ocr_from_base64(b64_img)
    
    if not result["success"]:
        print(f"OCR failed: {result.get('error', 'Unknown error')}")
        return
        
    lines = result["lines"]
    boxes = result["boxes"]
    
    print(f"Found {len(lines)} lines of text.")
    
    if not lines:
        print("No text found.")
        return
        
    # Analyze the boxes to find the structural boundaries
    # A box is {"x": int, "y": int, "width": int, "height": int}
    
    # Sort boxes by y coordinate
    boxes_with_text = list(zip(boxes, lines))
    boxes_with_text.sort(key=lambda item: item[0]["y"])
    
    print("\n--- Top 5 detected text lines ---")
    for box, text in boxes_with_text[:5]:
        print(f"Y: {box['y']} | Text: {text}")
        
    print("\n--- Bottom 5 detected text lines ---")
    for box, text in boxes_with_text[-5:]:
        print(f"Y: {box['y']} | Text: {text}")

    # We can detect the header if there's a significant gap between the first few lines and the rest.
    # Similarly for the footer.
    
    # Let's write the OCR output to a file so we can inspect it fully
    output_path = "dynamic_slice_ocr_report.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("--- ALL DETECTED LINES ORDERED BY Y-COORD ---\n")
        for box, text in boxes_with_text:
            f.write(f"Y: {box['y']:4d} | X: {box['x']:4d} | {text}\n")
            
    print(f"\nFull list saved to {output_path}")

if __name__ == "__main__":
    test_image = "C:/Users/wende/Documents/GitHub/BEn-app/server/src/data/pages/CAD_PDF_bilojz/page_016.png"
    test_dynamic_slice(test_image)
