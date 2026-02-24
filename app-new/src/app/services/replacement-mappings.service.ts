import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface ReplacementMapping {
  from: string;
  to: string;
  category: string;
  enabled: boolean;
}

const STORAGE_KEY = 'cured_replacement_mappings';

@Injectable({
  providedIn: 'root'
})
export class ReplacementMappingsService {

  private mappingsSubject = new BehaviorSubject<ReplacementMapping[]>([]);
  public mappings$ = this.mappingsSubject.asObservable();

  constructor() {
    this.loadMappings();
  }

  get mappings(): ReplacementMapping[] {
    return this.mappingsSubject.value;
  }

  private loadMappings(): void {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          this.mappingsSubject.next(parsed);
          return;
        }
      } catch (e) {
        console.warn('Failed to parse stored mappings, using defaults');
      }
    }
    // Initialize with defaults
    this.mappingsSubject.next(this.getDefaultMappings());
  }

  private saveMappings(): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.mappingsSubject.value));
  }

  private getDefaultMappings(): ReplacementMapping[] {
    return [
      // Unknown markers
      { from: '\\(unknown', to: '[?]', category: 'Unknown', enabled: true },
      { from: '(unknown)', to: '[?]', category: 'Unknown', enabled: true },
      { from: '<unknown>', to: '[?]', category: 'Unknown', enabled: true },
      { from: '\\unknown', to: '[?]', category: 'Unknown', enabled: true },
      // VLM markers
      { from: '<tbc>', to: '', category: 'VLM', enabled: true },
      // Ellipsis
      { from: 'x x x', to: '…', category: 'Ellipsis', enabled: true },
      { from: '......', to: '…', category: 'Ellipsis', enabled: true },
      { from: '...', to: '…', category: 'Ellipsis', enabled: true },
      // t variants → ṭ
      { from: 'ţ', to: 'ṭ', category: 'Consonants', enabled: true },
      { from: 'ț', to: 'ṭ', category: 'Consonants', enabled: true },
      { from: 'ť', to: 'ṭ', category: 'Consonants', enabled: true },
      // s variants → ṣ
      { from: 'ş', to: 'ṣ', category: 'Consonants', enabled: true },
      { from: 'ș', to: 'ṣ', category: 'Consonants', enabled: true },
      // h variants → ḫ
      { from: 'ḥ', to: 'ḫ', category: 'Consonants', enabled: true },
      // Vowels breve → macron
      { from: 'ă', to: 'ā', category: 'Vowels', enabled: true },
      { from: 'Ă', to: 'Ā', category: 'Vowels', enabled: true },
      { from: 'ĕ', to: 'ē', category: 'Vowels', enabled: true },
      { from: 'Ĕ', to: 'Ē', category: 'Vowels', enabled: true },
      { from: 'ĭ', to: 'ī', category: 'Vowels', enabled: true },
      { from: 'Ĭ', to: 'Ī', category: 'Vowels', enabled: true },
      { from: 'ŏ', to: 'ō', category: 'Vowels', enabled: true },
      { from: 'Ŏ', to: 'Ō', category: 'Vowels', enabled: true },
      { from: 'ŭ', to: 'ū', category: 'Vowels', enabled: true },
      { from: 'Ŭ', to: 'Ū', category: 'Vowels', enabled: true },
      // Aleph (glottal stop) - apostrophe + vowel → ʾ + vowel
      { from: "'a", to: 'ʾa', category: 'Aleph', enabled: true },
      { from: "'e", to: 'ʾe', category: 'Aleph', enabled: true },
      { from: "'i", to: 'ʾi', category: 'Aleph', enabled: true },
      { from: "'o", to: 'ʾo', category: 'Aleph', enabled: true },
      { from: "'u", to: 'ʾu', category: 'Aleph', enabled: true },
      { from: "'A", to: 'ʾA', category: 'Aleph', enabled: true },
      { from: "'E", to: 'ʾE', category: 'Aleph', enabled: true },
      { from: "'I", to: 'ʾI', category: 'Aleph', enabled: true },
      { from: "'O", to: 'ʾO', category: 'Aleph', enabled: true },
      { from: "'U", to: 'ʾU', category: 'Aleph', enabled: true },
      // Aleph - vowel + apostrophe → vowel + ʾ
      { from: "a'", to: 'aʾ', category: 'Aleph', enabled: true },
      { from: "e'", to: 'eʾ', category: 'Aleph', enabled: true },
      { from: "i'", to: 'iʾ', category: 'Aleph', enabled: true },
      { from: "o'", to: 'oʾ', category: 'Aleph', enabled: true },
      { from: "u'", to: 'uʾ', category: 'Aleph', enabled: true },
      { from: "A'", to: 'Aʾ', category: 'Aleph', enabled: true },
      { from: "E'", to: 'Eʾ', category: 'Aleph', enabled: true },
      { from: "I'", to: 'Iʾ', category: 'Aleph', enabled: true },
      { from: "O'", to: 'Oʾ', category: 'Aleph', enabled: true },
      { from: "U'", to: 'Uʾ', category: 'Aleph', enabled: true },
    ];
  }

  getCategories(): string[] {
    const cats = new Set(this.mappingsSubject.value.map(m => m.category));
    return Array.from(cats);
  }

  getMappingsByCategory(category: string): ReplacementMapping[] {
    return this.mappingsSubject.value.filter(m => m.category === category);
  }

  toggleMapping(mapping: ReplacementMapping): void {
    const mappings = this.mappingsSubject.value;
    const found = mappings.find(m => m.from === mapping.from && m.category === mapping.category);
    if (found) {
      found.enabled = !found.enabled;
      this.mappingsSubject.next([...mappings]);
      this.saveMappings();
    }
  }

  toggleCategoryMappings(category: string): void {
    const mappings = this.mappingsSubject.value;
    const categoryMappings = mappings.filter(m => m.category === category);
    const allEnabled = categoryMappings.every(m => m.enabled);
    categoryMappings.forEach(m => m.enabled = !allEnabled);
    this.mappingsSubject.next([...mappings]);
    this.saveMappings();
  }

  addMapping(from: string, to: string, category: string): void {
    if (!from) return;
    const mappings = this.mappingsSubject.value;
    mappings.push({
      from,
      to,
      category: category || 'Custom',
      enabled: true
    });
    this.mappingsSubject.next([...mappings]);
    this.saveMappings();
  }

  removeMapping(mapping: ReplacementMapping): void {
    const mappings = this.mappingsSubject.value;
    const idx = mappings.findIndex(m => m.from === mapping.from && m.category === mapping.category);
    if (idx >= 0) {
      mappings.splice(idx, 1);
      this.mappingsSubject.next([...mappings]);
      this.saveMappings();
    }
  }

  resetToDefaults(): void {
    this.mappingsSubject.next(this.getDefaultMappings());
    this.saveMappings();
  }

  /**
   * Apply silent corrections to text using enabled mappings.
   * These corrections are applied to the actual text, not just the preview.
   */
  applySilentCorrections(text: string): string {
    for (const mapping of this.mappingsSubject.value) {
      if (!mapping.enabled) continue;

      // Escape special regex characters in the 'from' string for literal matching
      const escaped = mapping.from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      // Handle backslash patterns specially (e.g., \unknown, \(unknown)
      const pattern = mapping.from.startsWith('\\')
        ? new RegExp(escaped.replace(/^\\\\/g, '\\\\'), 'g')
        : new RegExp(escaped, 'g');
      text = text.replace(pattern, mapping.to);
    }
    return text;
  }
}
