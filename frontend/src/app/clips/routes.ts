import {Route} from '@angular/router';
import {ClipsComponent} from './clips.component';

export default [{path: '', loadComponent: () => ClipsComponent}] as Route[];
