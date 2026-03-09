import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface VlmOcrHealthResponse {
  vlm_service_available: boolean;
  model: string;
  message: string;
}

export interface VlmOcrProcessResponse {
  success: boolean;
  text: string;
  processing_time_ms: number;
  model?: string;
  error?: string;
}

export interface VlmOcrCorrectionResponse {
  success: boolean;
  correction_id: string;
  message: string;
}

@Injectable({ providedIn: 'root' })
export class VlmOcrService {
  private baseUrl = '/vlm-ocr';

  constructor(private http: HttpClient) {}

  /**
   * Check if the VLM OCR service is available
   */
  checkHealth(): Observable<VlmOcrHealthResponse> {
    return this.http.get<VlmOcrHealthResponse>(
      `${environment.apiUrl}${this.baseUrl}/health`
    );
  }

  /**
   * Process an image with VLM OCR
   * @param imageBase64 Base64 encoded image
   * @param sourceType Type of document (ahw, cad, generic)
   */
  processImage(
    imageBase64: string,
    sourceType: 'ahw' | 'cad' | 'generic' = 'generic'
  ): Observable<VlmOcrProcessResponse> {
    return this.http.post<VlmOcrProcessResponse>(
      `${environment.apiUrl}${this.baseUrl}/process`,
      {
        image: imageBase64,
        source_type: sourceType,
        output_format: 'text'
      }
    );
  }

  /**
   * Process a PDF page with VLM OCR
   * @param file PDF file
   * @param page Page number (0-indexed)
   * @param sourceType Type of document
   */
  processPdf(
    file: File,
    page: number,
    sourceType: 'ahw' | 'cad' | 'generic' = 'generic'
  ): Observable<VlmOcrProcessResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('page', page.toString());
    formData.append('source_type', sourceType);

    return this.http.post<VlmOcrProcessResponse>(
      `${environment.apiUrl}${this.baseUrl}/process-pdf`,
      formData
    );
  }

  /**
   * Save a user correction for future fine-tuning
   * @param imageId Identifier for the image
   * @param originalText Original OCR output
   * @param correctedText User's corrected text
   * @param sourceType Type of document
   * @param pageNumber Optional page number
   */
  saveCorrection(
    imageId: string,
    originalText: string,
    correctedText: string,
    sourceType: 'ahw' | 'cad' | 'generic' = 'generic',
    pageNumber?: number
  ): Observable<VlmOcrCorrectionResponse> {
    return this.http.post<VlmOcrCorrectionResponse>(
      `${environment.apiUrl}${this.baseUrl}/save-correction`,
      {
        image_id: imageId,
        original_text: originalText,
        corrected_text: correctedText,
        source_type: sourceType,
        page_number: pageNumber
      }
    );
  }

  /**
   * Get the count of saved corrections
   */
  getCorrectionsCount(): Observable<{ count: number; message: string }> {
    return this.http.get<{ count: number; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/corrections/count`
    );
  }
}
