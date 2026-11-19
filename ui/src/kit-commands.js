// Pure command builder for the Final Project Kit tab. Never receives or emits secret values.
export const PREFIX_PATTERN=/^[a-z][a-z0-9]{2,9}$/;
export const PREFIX_PLACEHOLDER='PREFIX';
export const SECRET_SLOTS=[1,2,3,4,5];
export const STACKS=['node','python','java','go','static'];
export function isValidPrefix(prefix){return typeof prefix==='string'&&PREFIX_PATTERN.test(prefix);}
export function kitCommands(prefix){
 const valid=isValidPrefix(prefix),p=valid?prefix:PREFIX_PLACEHOLDER;
 const folder='project-kit';
 return {
  valid,prefix:p,folder,
  zipFile:'cpe334-project-kit-'+p+'.zip',
  prereq:'gcloud auth login\ngcloud config set project cpe-se-course-2026',
  // The kit lives inside the project folder; every command runs from the PROJECT folder, never from inside project-kit.
  unzip:'unzip cpe334-project-kit-'+p+'.zip',
  chmod:'chmod +x project-kit/*.sh',
  doctor:'./project-kit/kit.sh doctor',
  // One runnable command per stack (the student picks one); never a <a|b> placeholder that would run as a shell command.
  stacks:STACKS.map(s=>({stack:s,command:'./project-kit/kit.sh --stack '+s+' init'})),
  appEnv:'cp project-kit/app.env.example app.env',
  build:'./project-kit/kit.sh build',
  migrate:'./project-kit/kit.sh migrate',
  migrateExample:'MIGRATE_COMMAND=npx prisma migrate deploy',
  deploy:'./project-kit/kit.sh deploy\n./project-kit/kit.sh status\n./project-kit/kit.sh open',
  env:'./project-kit/kit.sh env set APP_MODE=production LOG_LEVEL=info',
  secretSlots:SECRET_SLOTS.map(n=>p+'-app-secret-'+n),
  secretAdd:'./project-kit/kit.sh secrets list\n./project-kit/kit.sh secrets add 1',
  secretMap:'./project-kit/kit.sh secrets map API_KEY 1\n./project-kit/kit.sh deploy',
  logs:'./project-kit/kit.sh logs',
  rollback:'./project-kit/kit.sh rollback',
  dryRun:'./project-kit/kit.sh --dry-run deploy',
 };
}
