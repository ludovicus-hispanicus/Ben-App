import { ComponentFixture, TestBed } from '@angular/core/testing';

import { LetterViewerComponent } from './letter-viewer.component';

describe('LetterViewerComponent', () => {
  let component: LetterViewerComponent;
  let fixture: ComponentFixture<LetterViewerComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ LetterViewerComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(LetterViewerComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
