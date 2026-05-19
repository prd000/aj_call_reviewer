import { NavLink } from 'react-router-dom'
import './TopNav.css'

export default function TopNav() {
  return (
    <nav className="top-nav">
      <div className="top-nav__inner">
        <span className="top-nav__brand">Call Reviewer</span>
        <div className="top-nav__links">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              isActive ? 'top-nav__link top-nav__link--active' : 'top-nav__link'
            }
          >
            Upload
          </NavLink>
          <NavLink
            to="/history"
            className={({ isActive }) =>
              isActive ? 'top-nav__link top-nav__link--active' : 'top-nav__link'
            }
          >
            History
          </NavLink>
        </div>
      </div>
    </nav>
  )
}
