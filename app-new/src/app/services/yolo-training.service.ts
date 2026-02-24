import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  DatasetCreateRequest,
  DatasetCreateResponse,
  DatasetListItem,
  DatasetStats,
  ImageUploadRequest,
  ImageUploadResponse,
  ModelListResponse,
  PredictRequest,
  PredictResponse,
  TrainingJob,
  TrainingStartRequest,
  TrainingStartResponse,
  TrainingStatusResponse,
  YoloAnnotation,
  YoloHealthResponse,
  AutoAnnotateRequest,
  AutoAnnotateResponse,
  AutoAnnotateStatus
} from '../models/yolo-training';

@Injectable({
  providedIn: 'root'
})
export class YoloTrainingService {
  public baseUrl = '/yolo';

  constructor(private http: HttpClient) { }

  // ============== Health Check ==============

  checkHealth(): Observable<YoloHealthResponse> {
    return this.http.get<YoloHealthResponse>(
      `${environment.apiUrl}${this.baseUrl}/health`
    );
  }

  // ============== Dataset Management ==============

  createDataset(request: DatasetCreateRequest): Observable<DatasetCreateResponse> {
    return this.http.post<DatasetCreateResponse>(
      `${environment.apiUrl}${this.baseUrl}/datasets`,
      request
    );
  }

  listDatasets(): Observable<DatasetListItem[]> {
    return this.http.get<DatasetListItem[]>(
      `${environment.apiUrl}${this.baseUrl}/datasets`
    );
  }

  getDatasetStats(datasetName: string): Observable<DatasetStats> {
    return this.http.get<DatasetStats>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/stats`
    );
  }

  uploadImage(
    datasetName: string,
    imageBase64: string,
    filename: string,
    annotations: YoloAnnotation[],
    split: 'train' | 'val' = 'train'
  ): Observable<ImageUploadResponse> {
    const request: ImageUploadRequest = {
      image: imageBase64,
      filename: filename,
      annotations: annotations,
      split: split
    };
    return this.http.post<ImageUploadResponse>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images`,
      request
    );
  }

  addClassesToDataset(datasetName: string, classes: (string | { name: string; color?: string })[]): Observable<{
    success: boolean;
    dataset_id: string;
    classes: { id: number; name: string; color?: string }[];
    added: string[];
    message: string;
  }> {
    return this.http.post<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/classes`,
      { classes }
    );
  }

  updateClassColor(datasetName: string, classId: number, color: string): Observable<{
    success: boolean;
    dataset_id: string;
    classes: { id: number; name: string; color?: string }[];
    message: string;
  }> {
    return this.http.put<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/classes/${classId}/color`,
      { color }
    );
  }

  renameClass(datasetName: string, classId: number, newName: string): Observable<{
    success: boolean;
    dataset_id: string;
    classes: { id: number; name: string; color?: string }[];
    message: string;
  }> {
    return this.http.put<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/classes/${classId}/name`,
      { name: newName }
    );
  }

  updateDatasetMetadata(datasetName: string, data: { name?: string; description?: string; curated?: boolean }): Observable<{
    success: boolean;
    dataset_id: string;
    name: string;
    description: string;
    curated: boolean;
    message: string;
  }> {
    return this.http.put<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/metadata`,
      data
    );
  }

  deleteDataset(datasetName: string): Observable<{ success: boolean; message: string }> {
    return this.http.delete<{ success: boolean; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}`
    );
  }

  /**
   * List all images in a dataset with their annotation counts.
   */
  listDatasetImages(datasetName: string): Observable<{
    success: boolean;
    images: Array<{
      image_id: string;
      filename: string;
      split: string;
      annotation_count: number;
      has_annotations: boolean;
      curated: boolean;
    }>;
    total: number;
    with_annotations: number;
    without_annotations: number;
  }> {
    return this.http.get<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images`
    );
  }

  /**
   * Get a specific image with its annotations from a dataset.
   */
  getDatasetImage(datasetName: string, imageId: string, split?: string): Observable<{
    success: boolean;
    image_id: string;
    filename: string;
    split: string;
    image_base64: string;
    image_width: number;
    image_height: number;
    annotations: Array<{
      class_id: number;
      class_name: string;
      x_center: number;
      y_center: number;
      width: number;
      height: number;
    }>;
    annotation_count: number;
    curated: boolean;
  }> {
    let url = `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images/${imageId}`;
    if (split) {
      url += `?split=${split}`;
    }
    return this.http.get<any>(url);
  }

  /**
   * Update annotations for an existing image in a dataset.
   */
  updateImageAnnotations(
    datasetName: string,
    imageId: string,
    annotations: YoloAnnotation[],
    split?: string
  ): Observable<{
    success: boolean;
    image_id: string;
    split: string;
    annotation_count: number;
    message: string;
  }> {
    return this.http.put<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images/${imageId}`,
      { annotations, split }
    );
  }

  /**
   * Mark or unmark an image as curated (reviewed).
   */
  toggleImageCurated(datasetName: string, imageId: string, curated: boolean): Observable<{
    success: boolean;
    image_id: string;
    curated: boolean;
    curated_count: number;
  }> {
    return this.http.put<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images/${imageId}/curated`,
      { curated }
    );
  }

  /**
   * Delete a specific image from a dataset.
   */
  deleteDatasetImage(datasetName: string, imageId: string): Observable<{ success: boolean; message: string }> {
    return this.http.delete<{ success: boolean; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/images/${imageId}`
    );
  }

  /**
   * Remove all images without annotations from a dataset.
   */
  cleanupEmptyImages(datasetName: string): Observable<{
    success: boolean;
    removed_count: number;
    removed_images: string[];
    message: string;
  }> {
    return this.http.post<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/cleanup`,
      {}
    );
  }

  // ============== Dataset Download ==============

  downloadDataset(datasetName: string, format: 'training' | 'snippets' = 'training'): void {
    const url = `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/download?format=${format}`;
    window.open(url, '_blank');
  }

  // ============== Save Snippets to Library ==============

  saveSnippetsToLibrary(datasetName: string, projectId?: string, projectName?: string): Observable<{
    project_id: string;
    name: string;
    snippet_count: number;
    manifest: any[];
  }> {
    const params: any = {};
    if (projectId) params.project_id = projectId;
    if (projectName) params.project_name = projectName;
    return this.http.post<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/${datasetName}/save-to-library`,
      {},
      { params }
    );
  }

  // ============== Dataset Merge ==============

  mergeDatasets(sourceDatasets: string[], targetName: string, description?: string): Observable<any> {
    return this.http.post<any>(
      `${environment.apiUrl}${this.baseUrl}/datasets/merge`,
      { source_datasets: sourceDatasets, target_name: targetName, description }
    );
  }

  // ============== Model Management ==============

  listModels(): Observable<ModelListResponse> {
    return this.http.get<ModelListResponse>(
      `${environment.apiUrl}${this.baseUrl}/models`
    );
  }

  deleteModel(modelName: string): Observable<{ success: boolean; message: string }> {
    return this.http.delete<{ success: boolean; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/models/${modelName}`
    );
  }

  activateModel(modelName: string): Observable<{ success: boolean; model_name: string }> {
    return this.http.post<{ success: boolean; model_name: string }>(
      `${environment.apiUrl}${this.baseUrl}/models/${modelName}/activate`,
      {}
    );
  }

  getActiveModel(): Observable<{ active: boolean; model_name: string | null }> {
    return this.http.get<{ active: boolean; model_name: string | null }>(
      `${environment.apiUrl}${this.baseUrl}/models/active`
    );
  }

  // ============== Training ==============

  startTraining(request: TrainingStartRequest): Observable<TrainingStartResponse> {
    return this.http.post<TrainingStartResponse>(
      `${environment.apiUrl}${this.baseUrl}/train`,
      request
    );
  }

  getTrainingStatus(trainingId: string): Observable<TrainingStatusResponse> {
    return this.http.get<TrainingStatusResponse>(
      `${environment.apiUrl}${this.baseUrl}/train/${trainingId}/status`
    );
  }

  /**
   * Subscribe to training progress via Server-Sent Events.
   * Returns an EventSource that emits progress updates.
   */
  streamTrainingProgress(trainingId: string): EventSource {
    const url = `${environment.apiUrl}${this.baseUrl}/train/${trainingId}/stream`;
    return new EventSource(url);
  }

  listTrainingJobs(limit: number = 20): Observable<TrainingJob[]> {
    return this.http.get<TrainingJob[]>(
      `${environment.apiUrl}${this.baseUrl}/train/jobs`,
      { params: { limit: limit.toString() } }
    );
  }

  cancelTraining(trainingId: string): Observable<{ success: boolean; message: string }> {
    return this.http.post<{ success: boolean; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/train/${trainingId}/cancel`,
      {}
    );
  }

  // ============== Training Logs ==============

  getTrainingLogs(trainingId: string): Observable<{
    success: boolean;
    epochs: Array<{
      epoch: number;
      box_loss: number;
      cls_loss: number;
      dfl_loss: number;
      precision: number;
      recall: number;
      mAP50: number;
      mAP50_95: number;
      val_box_loss: number;
      val_cls_loss: number;
    }>;
    message?: string;
  }> {
    return this.http.get<any>(
      `${environment.apiUrl}${this.baseUrl}/train/${trainingId}/logs`
    );
  }

  // ============== Auto-Annotate ==============

  startAutoAnnotate(request: AutoAnnotateRequest): Observable<AutoAnnotateResponse> {
    return this.http.post<AutoAnnotateResponse>(
      `${environment.apiUrl}${this.baseUrl}/auto-annotate`,
      request
    );
  }

  getAutoAnnotateStatus(jobId: string): Observable<AutoAnnotateStatus> {
    return this.http.get<AutoAnnotateStatus>(
      `${environment.apiUrl}${this.baseUrl}/auto-annotate/${jobId}/status`
    );
  }

  // ============== Inference ==============

  predict(
    imageBase64: string,
    model: string = 'default',
    confidence: number = 0.25,
    iou: number = 0.45
  ): Observable<PredictResponse> {
    const request: PredictRequest = {
      image: imageBase64,
      model: model,
      confidence: confidence,
      iou: iou
    };
    return this.http.post<PredictResponse>(
      `${environment.apiUrl}${this.baseUrl}/predict`,
      request
    );
  }

  // ============== Utility Methods ==============

  /**
   * Convert a File to base64 string.
   */
  fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        const result = reader.result as string;
        // Remove the data URL prefix (e.g., "data:image/png;base64,")
        const base64 = result.split(',')[1];
        resolve(base64);
      };
      reader.onerror = error => reject(error);
    });
  }

  /**
   * Convert pixel coordinates to normalized YOLO format.
   */
  pixelToYolo(
    x: number,
    y: number,
    width: number,
    height: number,
    imageWidth: number,
    imageHeight: number
  ): YoloAnnotation {
    return {
      class_id: 0,  // Will be set by caller
      x_center: (x + width / 2) / imageWidth,
      y_center: (y + height / 2) / imageHeight,
      width: width / imageWidth,
      height: height / imageHeight
    };
  }

  /**
   * Convert YOLO normalized coordinates to pixel coordinates.
   */
  yoloToPixel(
    annotation: YoloAnnotation,
    imageWidth: number,
    imageHeight: number
  ): { x: number; y: number; width: number; height: number } {
    const width = annotation.width * imageWidth;
    const height = annotation.height * imageHeight;
    const x = annotation.x_center * imageWidth - width / 2;
    const y = annotation.y_center * imageHeight - height / 2;
    return { x, y, width, height };
  }

}
