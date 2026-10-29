export interface PageInfo {
  filename: string;
  page_number: number;
  thumbnail_url: string;
  full_url: string;
  file_size: number;
  modified_at: string;
  file_type: string;
}

export interface ProjectInfo {
  project_id: string;
  name: string;
  image_count: number;
  created_at: string;
  parent_id: string | null;
  children_count: number;
}

export interface ProjectTreeNode {
  project_id: string;
  name: string;
  image_count: number;
  created_at: string;
  parent_id: string | null;
  children_count: number;
  total_image_count: number;
  children: ProjectTreeNode[];
  expanded?: boolean;  // UI state
}

export interface ProjectDetail {
  project_id: string;
  name: string;
  pages: PageInfo[];
  total_pages: number;
}

export interface ProjectListResponse {
  projects: ProjectInfo[];
}

export interface UploadResponse {
  project_id: string;
  name: string;
  page_count: number;
  message: string;
}

export interface SelectedPage {
  project_id: string;
  project_name: string;
  page_number: number;
  filename: string;
  image_url: string;
}
