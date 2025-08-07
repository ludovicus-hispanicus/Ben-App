import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SmartSelectorComponent } from './smart-selector.component';

describe('SmartSelectorComponent', () => {
  let component: SmartSelectorComponent;
  let fixture: ComponentFixture<SmartSelectorComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ SmartSelectorComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(SmartSelectorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
