import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CuredComponent } from './cured.component';


describe('CuredComponent', () => {
  let component: CuredComponent;
  let fixture: ComponentFixture<CuredComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ CuredComponent ]
    })
    .compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(CuredComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
