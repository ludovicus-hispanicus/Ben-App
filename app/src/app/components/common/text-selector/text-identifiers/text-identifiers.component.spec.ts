import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TextIdentifiersComponent } from './text-identifiers.component';

describe('TextIdentifiersComponent', () => {
  let component: TextIdentifiersComponent;
  let fixture: ComponentFixture<TextIdentifiersComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ TextIdentifiersComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(TextIdentifiersComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
