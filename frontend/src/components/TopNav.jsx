import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './TopNav.css'

export default function TopNav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

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
          {user?.role === 'bds_rep' && (
            <NavLink
              to="/management"
              className={({ isActive }) =>
                isActive ? 'top-nav__link top-nav__link--active' : 'top-nav__link'
              }
            >
              Management
            </NavLink>
          )}
        </div>
        {user && (
          <div className="top-nav__user">
            <span className="top-nav__user-name">{user.name}</span>
            <button className="top-nav__logout" onClick={handleLogout}>
              Logout
            </button>
          </div>
        )}
      </div>
    </nav>
  )
}
