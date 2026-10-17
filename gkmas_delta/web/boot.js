// The live UI is served by the local backend. The mock demo needs ?demo=1.
const frontendScript=document.createElement('script');
const demoMode=new URLSearchParams(location.search).get('demo')==='1';
frontendScript.src=demoMode?'app.js':'live.js';
document.head.append(frontendScript);

