/** The course the student is working on. It is a plain cookie so server pages (the dashboard) and
 *  the chat can both read it; it only ever holds a subject id, and the server checks that id
 *  against the student's own subjects before using it. */
export const COURSE_COOKIE = "mindnest_course";

export function setCourseCookie(id: string | null): void {
  document.cookie = id
    ? `${COURSE_COOKIE}=${id}; path=/; max-age=31536000; samesite=lax`
    : `${COURSE_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

export function readCourseCookie(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${COURSE_COOKIE}=([^;]*)`));
  return match && match[1] ? match[1] : null;
}
