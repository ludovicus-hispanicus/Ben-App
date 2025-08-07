import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TextCreatorComponent } from './text-creator.component';

describe('TextCreatorComponent', () => {
  let component: TextCreatorComponent;
  let fixture: ComponentFixture<TextCreatorComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ TextCreatorComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(TextCreatorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
