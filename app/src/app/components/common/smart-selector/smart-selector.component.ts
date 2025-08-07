import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { map, startWith } from 'rxjs/operators';

import { SignData } from '../../amendment/letter-viewer/letter-viewer.component';


export interface SelectorState {
  value: string,
  label?: string
}


@Component({
  selector: 'smart-selector',
  templateUrl: './smart-selector.component.html',
  styleUrls: ['./smart-selector.component.scss']
})
export class SmartSelectorComponent implements OnInit {

  @Output() selectionChange: EventEmitter<SelectorState> = new EventEmitter();
  @Output() valueChange: EventEmitter<string> = new EventEmitter();


  @Input() public showCustomFont: boolean = true;
  @Input() public hint: string = "Type the sign"
  @Input() public resetAfterSelected: boolean = true;
  @Input() public minLenToFilter: number = 1;
  @Input() public width = ""

  private _states: SelectorState[];
  stateCtrl = new FormControl();

  @Input() 
  public set signs(val: SignData[] ) {
    const states =  val.map((letterData) => {
      return { value: letterData.letter, label: letterData.symbol };
    });
    this._states = states;
    this.stateCtrl.reset();
  }

  @Input()
  public set states(val: SelectorState[]) {
    this._states = val;
    this.stateCtrl.reset();
  }

  @Input()
  public set rawStates(states: string[]) {
    this._states = states.map((state) => {
      return {value: state};
    });
  }

  get states(): any { 
    return this._states;
  }

  public filteredStates: Observable<SelectorState[]>;

  constructor() {
      this.filteredStates = this.stateCtrl.valueChanges.pipe(
          startWith(''),
          map(state => state != null && state.length >= this.minLenToFilter
             ? this._filterStates(state) 
             : this._getTopFiveStates())
      );
      this.stateCtrl.valueChanges.subscribe(newValue => this.valueChange.emit(newValue))
  }

  private _filterStates(value: string): SelectorState[] {
    const filterValue = value.toLowerCase();
    if(filterValue.length < 1 && this.minLenToFilter >= 1) {
      return [];
    }
    return this.states.filter(state => state.value.toLowerCase().startsWith(filterValue));
  }

  private _getTopFiveStates(): SelectorState[] {
    return this.states.slice(-5);
  }

  ngOnInit(): void {
  }

  selectionChanged(state) {
    this.selectionChange.emit(state);
    if(this.resetAfterSelected) {
      this.stateCtrl.setValue("");
    }
  }

  getFont() {
    if(this.showCustomFont) {
      return 'Esagil'
    } else {
      return "Arial"
    }
  }

}
