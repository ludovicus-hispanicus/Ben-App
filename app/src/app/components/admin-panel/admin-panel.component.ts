import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { ModuleService } from '../../services/module.service';

@Component({
  selector: 'app-admin-panel',
  templateUrl: './admin-panel.component.html',
  styleUrls: ['./admin-panel.component.scss']
})
export class AdminPanelComponent implements OnInit {

  constructor(public router: Router, public moduleService: ModuleService) { }

  ngOnInit(): void {
    // Placeholder - global activities will be loaded here
  }
}
