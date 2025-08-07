import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TextSelectorComponent } from './text-selector.component';

describe('TextSelectorComponent', () => {
  let component: TextSelectorComponent;
  let fixture: ComponentFixture<TextSelectorComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ TextSelectorComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(TextSelectorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
