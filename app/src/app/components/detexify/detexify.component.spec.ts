import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DetexifyComponent } from './detexify.component';

describe('DetexifyComponent', () => {
  let component: DetexifyComponent;
  let fixture: ComponentFixture<DetexifyComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ DetexifyComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(DetexifyComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
