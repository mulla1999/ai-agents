from . import admin, applications, assistant, auth, dashboard, extension, interview, jobs, outreach, resume_builder, resumes, settings, skill_gaps

ROUTERS = [auth.router, admin.router, dashboard.router, jobs.router, resumes.router, applications.router,
           outreach.router, settings.router, assistant.router, extension.router, resume_builder.router, interview.router,
           skill_gaps.router]

__all__ = ["ROUTERS"]
