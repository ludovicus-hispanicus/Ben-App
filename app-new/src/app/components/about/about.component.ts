import { Component, OnInit } from '@angular/core';
import { AboutService } from 'src/app/services/about.service';

@Component({
  selector: 'app-about',
  templateUrl: './about.component.html',
  styleUrls: ['./about.component.scss']
})
export class AboutComponent implements OnInit {

  constructor(private AboutService: AboutService) { }

  public markdown: string = "# Loading...";

  ngOnInit(): void {
    this.AboutService.readme().subscribe(data => {
      this.markdown = data;
    });
  }

}
