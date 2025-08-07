import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MetaViewerComponent } from './meta-viewer.component';

describe('MetaViewerComponent', () => {
  let component: MetaViewerComponent;
  let fixture: ComponentFixture<MetaViewerComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ MetaViewerComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(MetaViewerComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
