import {Injectable} from '@angular/core';
import {HttpEvent, HttpInterceptor, HttpHandler, HttpRequest, HTTP_INTERCEPTORS, HttpResponse} from '@angular/common/http';
import {Observable} from 'rxjs';
import { NotificationService } from '../services/notification.service';

import {HttpErrorResponse, } from '@angular/common/http';
import { throwError} from 'rxjs';
import {catchError, map} from "rxjs/operators";

@Injectable()
export class ErrorInterceptor implements HttpInterceptor {

    constructor(private notificationService: NotificationService) {

    }

    intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
        // Requests can opt out of the global error toast by sending the
        // `X-Silent-Errors` header (e.g. probe-style lookups where a 404 is an
        // expected branch, not a failure). Strip the marker before forwarding.
        const silent = request.headers.has('X-Silent-Errors');
        if (silent) {
            request = request.clone({ headers: request.headers.delete('X-Silent-Errors') });
        }
        return next.handle(request).pipe(
            catchError((error: HttpErrorResponse) => {
                let errorMsg = '';
                if (error.error instanceof ErrorEvent) {
                    if (!silent) console.log('This is client side error');
                    errorMsg = `Error: ${error.error.message}`;
                } else {
                    if (!silent) {
                        console.log('This is server side error');
                        console.log(error.error.detail);
                    }
                    errorMsg = `Server error. Details: ${error.error.detail}`;
                }
                if (!silent) {
                    this.notificationService.showError(`${errorMsg}`);
                }
                return throwError(errorMsg);
            })
        )
    }
}

export const errorInterceptorProviders = [
    { provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true }
  ];