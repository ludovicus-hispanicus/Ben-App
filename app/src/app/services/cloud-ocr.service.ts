import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import { VlmOcrProcessResponse } from './vlm-ocr.service';

export type CloudProvider = 'openai' | 'anthropic' | 'google';

export interface CloudOcrModel {
  id: string;
  label: string;
  provider: CloudProvider;
}

export interface CloudOcrProvider {
  id: CloudProvider;
  label: string;
  icon: string;
  models: CloudOcrModel[];
}

export const CLOUD_PROVIDERS: CloudOcrProvider[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    icon: 'smart_toy',
    models: [
      { id: 'gpt-4o', label: 'GPT-4o (recommended)', provider: 'openai' },
      { id: 'gpt-4o-mini', label: 'GPT-4o Mini (faster)', provider: 'openai' },
      { id: 'gpt-4.1', label: 'GPT-4.1 (latest)', provider: 'openai' },
    ]
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    icon: 'psychology',
    models: [
      { id: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5 (recommended)', provider: 'anthropic' },
      { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (fastest)', provider: 'anthropic' },
      { id: 'claude-opus-4-6', label: 'Claude Opus 4.6 (most capable)', provider: 'anthropic' },
    ]
  },
  {
    id: 'google',
    label: 'Google',
    icon: 'auto_awesome',
    models: [
      { id: 'gemini-3.0-pro', label: 'Gemini 3.0 Pro (flagship)', provider: 'google' },
      { id: 'gemini-3.0-flash', label: 'Gemini 3.0 Flash (fast)', provider: 'google' },
      { id: 'gemini-3.0-pro-image', label: 'Gemini 3.0 Pro Image', provider: 'google' },
      { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', provider: 'google' },
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash (recommended)', provider: 'google' },
    ]
  }
];

const API_KEYS_STORAGE_KEY = 'ben_cloud_ocr_api_keys';

@Injectable({ providedIn: 'root' })
export class CloudOcrService {
  private baseUrl = '/cloud-ocr';

  constructor(private http: HttpClient) {}

  processImage(
    imageBase64: string,
    provider: CloudProvider,
    model: string,
    apiKey: string,
    sourceType: 'ahw' | 'cad' | 'generic' = 'generic'
  ): Observable<VlmOcrProcessResponse> {
    return this.http.post<VlmOcrProcessResponse>(
      `${environment.apiUrl}${this.baseUrl}/process`,
      {
        image: imageBase64,
        provider,
        model,
        api_key: apiKey,
        source_type: sourceType,
      }
    );
  }

  /** Load saved API keys from localStorage */
  loadApiKeys(): { [provider: string]: string } {
    try {
      const stored = localStorage.getItem(API_KEYS_STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  }

  /** Save API keys to localStorage */
  saveApiKeys(keys: { [provider: string]: string }): void {
    localStorage.setItem(API_KEYS_STORAGE_KEY, JSON.stringify(keys));
  }
}
